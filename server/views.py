"""保密的唯一出口（SPEC A7、B3、CODING_RULES S1）：一律白名單組資料，新增欄位預設不送。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from server import disguise, rules
from server.enums import Action, Channel, Mode, Role, Step
from server.events import Event, EventType
from server.roles import is_wolf, night_step_pairs, roles_acting_in
from server.state import GameState, PlayerState

Message = dict[str, Any]

_STEP_ACTIONS = {
    Step.WOLF: Action.WOLF_PICK,
    Step.SEER: Action.SEER_CHECK,
    Step.WITCH: Action.WITCH_ACT,
    Step.HUNTER: Action.HUNTER_SHOOT,
    Step.VOTE: Action.VOTE_CAST,
}


class ViewerKind(StrEnum):
    HOST = "host"
    PLAYER = "player"
    OBSERVER = "observer"  # 旁觀者、無管理員模式另一台裝置的管理員操作


@dataclass(frozen=True)
class Viewer:
    kind: ViewerKind
    player_id: str | None = None


HOST_VIEWER = Viewer(ViewerKind.HOST)
OBSERVER_VIEWER = Viewer(ViewerKind.OBSERVER)


def _me(state: GameState, viewer: Viewer) -> PlayerState | None:
    if viewer.player_id is None or not state.has_player(viewer.player_id):
        return None
    return state.player(viewer.player_id)


def _ended(state: GameState) -> bool:
    return state.step is Step.END


def _can_see_clock(state: GameState, viewer: Viewer) -> bool:
    """非行動者夜晚看不到秒數（SPEC C8.2），避免從快慢推斷誰在操作。"""
    if not rules.is_night_step(state.step) or viewer.kind is ViewerKind.HOST:
        return True
    return viewer.player_id in state.actors


def _timers(state: GameState, viewer: Viewer) -> Message:
    if not _can_see_clock(state, viewer):
        return {}
    timing = state.timers
    return {
        "opens_at": timing.opens_at,
        "deadline": timing.deadline,
        "grace_until": timing.grace_until,
    }


def _public_player(player: PlayerState, reveal_all: bool) -> Message:
    row: Message = {
        "id": player.id,
        "name": player.name,
        "seat": player.seat,
        "alive": player.alive,
    }
    if reveal_all:
        row["role"] = player.role.value
    elif not player.alive:
        row["public_role"] = rules.public_role(player.role).value
    return row


def night_plan(state: GameState) -> list[str]:
    """今晚進度條的點（SPEC C8.4）。死亡公開，所以這份資訊本來就公開。"""
    plan = []
    for step, _ in night_step_pairs():
        acting = roles_acting_in(step)
        if any(p.alive and p.role in acting for p in state.players):
            plan.append(step.value)
    return plan


def _progress(state: GameState) -> Message:
    if state.step is Step.DEAL:
        return {"done": sum(1 for p in state.players if p.acked), "total": len(state.players)}
    if state.step is Step.VOTE:
        return {"done": len(state.vote_round().ballots), "total": len(state.actors)}
    return {}


def _public_actors(state: GameState) -> list[str]:
    """白天的行動者（獵人、發言者）本來就公開；夜晚不送（SPEC C8.4）。"""
    if rules.is_night_step(state.step) or state.step is Step.VOTE or state.step is Step.DEAL:
        return []
    return list(state.actors)


def public_block(state: GameState) -> Message:
    """人人可見的部分：每次事件只算一次（CODING_RULES P2）。"""
    pause = state.pause
    return {
        "mode": state.mode.value,
        "step": state.step.value,
        "step_seq": state.step_seq,
        "round_no": state.round_no,
        "line_id": state.line_id,
        "narrator_id": state.narrator_id,
        "speaker": state.current_speaker,
        "speak_queue": list(state.speak_queue),
        "public_actors": _public_actors(state),
        "night_plan": night_plan(state),
        "progress": _progress(state),
        "paused": ({"reason": pause.reason.value, "resume_at": pause.resume_at} if pause else None),
        "players": [_public_player(p, _ended(state)) for p in state.players],
        "history": public_history(state),
        "winner": state.winner.value if state.winner else None,
    }


def public_history(state: GameState) -> list[Message]:
    """玩家 → 紀錄（SPEC C3）：每回合公開的死亡名單與投票明細，不含死因。"""
    rows = []
    for votes in state.votes:
        deaths = [p.id for p in state.players if p.death_round == votes.round_no]
        row: Message = {"round_no": votes.round_no, "deaths": deaths}
        if votes.revealed:
            row["ballots"] = dict(votes.ballots)
            row["exiled"] = votes.exiled
        rows.append(row)
    return rows


def _wolf_block(state: GameState, player: PlayerState) -> Message:
    pack = [p.id for p in state.players if is_wolf(p.role)]
    block: Message = {"pack": pack}
    if player.alive and state.step is Step.WOLF:
        block.update(_wolf_picks(state))
    return block


def _wolf_picks(state: GameState) -> Message:
    night = state.night()
    return {
        "picks": dict(night.wolf_picks),
        "confirming_until": state.timers.confirm_until,
        "decided": night.wolf_decided,
        "decided_target": night.wolf_target if night.wolf_decided else None,
    }


def _seer_block(state: GameState) -> Message:
    return {
        "checks": [
            {"round_no": n.round_no, "target": n.seer_target, "is_wolf": n.seer_is_wolf}
            for n in state.nights
            if n.seer_target is not None
        ]
    }


def _witch_block(state: GameState, player: PlayerState) -> Message:
    block: Message = {
        "antidote_used": state.witch_antidote_used,
        "poison_used": state.witch_poison_used,
    }
    if state.step is Step.WITCH and player.alive:
        options = rules.witch_options(state, player.id)
        block.update(
            attacked=options.attacked,
            attack_known=not state.witch_antidote_used,
            can_save=options.can_save,
            can_poison=options.can_poison,
            acted=state.night().witch_acted,
        )
    return block


def _disguise_block(state: GameState) -> Message:
    assert state.disguise is not None
    return {"target": state.disguise.target_id, "rounds_left": state.disguise.rounds_left}


def _me_block(state: GameState, player: PlayerState) -> Message:
    is_actor = player.id in state.actors
    block: Message = {
        "id": player.id,
        "role": player.role.value,
        "alive": player.alive,
        "is_actor": is_actor,
        "done": player.id in state.done,
        "acked": player.acked,
        "can_bet": rules.can_bet(state, player.id) and not _ended(state),
    }
    action = _STEP_ACTIONS.get(state.step)
    if is_actor and action is not None:
        block["eligible_targets"] = rules.eligible_targets(state, player.id, action)
    if state.step is Step.VOTE and state.votes and player.id in state.vote_round().ballots:
        votes = state.vote_round()
        block["my_vote"] = {
            "target": votes.ballots[player.id],
            "can_change": player.id not in votes.changed,
        }
    if player.id in state.bets:
        bet = state.bets[player.id]
        block["my_bet"] = {"wolves": list(bet.wolves), "faceless_guess": bet.faceless}
    if is_wolf(player.role):
        block["wolf_pack"] = _wolf_block(state, player)
    if player.role is Role.SEER:
        block["seer_info"] = _seer_block(state)
    if player.role is Role.WITCH:
        block["witch_info"] = _witch_block(state, player)
    if player.role is Role.FACELESS and state.disguise is not None:
        block["disguise_info"] = _disguise_block(state)
        block["can_disguise"] = disguise.can_disguise(state, player.id)
    return block


def host_block(state: GameState) -> Message:
    """上帝主持人看得到全部（SPEC A3），押注例外（SPEC A13）。"""
    block: Message = {
        "actors": list(state.actors),
        "done": list(state.done),
        "timed_out": state.timed_out,
        "players": [
            {
                "id": p.id,
                "role": p.role.value,
                "alive": p.alive,
                "death_cause": p.death_cause.value if p.death_cause else None,
                "acked": p.acked,
            }
            for p in state.players
        ],
        "witch": {
            "antidote_used": state.witch_antidote_used,
            "poison_used": state.witch_poison_used,
        },
        "nights": [n.model_dump() for n in state.nights],
        "votes": [v.model_dump() for v in state.votes],
        "disguise": (
            state.disguise.model_dump(mode="json") if state.disguise is not None else None
        ),
        "timers": state.timers.model_dump(),
    }
    if state.step is Step.WOLF:
        block["wolf_status"] = _wolf_picks(state)
    return block


def chat_message(msg: Message, viewer: Viewer, state: GameState) -> Message | None:
    """聊天過濾（SPEC A6、A7、A9）：假扮訊息對他人只有 display_player_id。回 None 表示看不到。"""
    channel = Channel(msg["channel"])
    ended = _ended(state)
    me = _me(state, viewer)
    is_host = viewer.kind is ViewerKind.HOST
    wolf_reader = ended or is_host or (me is not None and is_wolf(me.role))
    if channel is Channel.WOLF and not wolf_reader:
        return None
    author_is_me = viewer.player_id is not None and msg["real_author"] == viewer.player_id
    disguised = msg["disguise_period"] is not None
    out: Message = {
        "t": "chat.msg",
        "id": msg["id"],
        "channel": msg["channel"],
        "display_player_id": msg["display"],
        "is_host_msg": msg["is_host"],
        "kind": msg["kind"],
        "content": msg["content"],
        "media_id": msg["media_id"],
        "ts": msg["ts"],
    }
    # 假扮者本人的泡泡要標註；對其他人（含被假扮者）不可標 mine（SPEC A6）
    if author_is_me:
        out["mine"] = True
        if disguised:
            out["disguised_by_me"] = True
    if disguised and (is_host or ended):
        out["real_author"] = msg["real_author"]
    return out


def truth_block(state: GameState, chat: Sequence[Message] = ()) -> Message:
    """結算的看真相（SPEC A8.7）。只在 END 之後才會被呼叫。"""
    roles = {p.id: p.role for p in state.players}
    return {
        "roles": {pid: role.value for pid, role in roles.items()},
        "death_causes": {
            p.id: p.death_cause.value for p in state.players if p.death_cause is not None
        },
        "disguise": (
            state.disguise.model_dump(mode="json") if state.disguise is not None else None
        ),
        "nights": [n.model_dump() for n in state.nights],
        "votes": [v.model_dump() for v in state.votes],
        "disguised_messages": [
            {"id": m["id"], "real_author": m["real_author"], "display": m["display"]}
            for m in chat
            if m["disguise_period"] is not None
        ],
        "bets": [
            {
                "player_id": score.player_id,
                "score": score.score,
                "rank": score.rank,
                **state.bets[score.player_id].model_dump(),
            }
            for score in rules.score_bets(state.bets, roles)
        ],
    }


def build(state: GameState, viewer: Viewer, chat: Sequence[Message] = ()) -> Message:
    """該觀看者的完整可見狀態（SPEC B4）：連線、重連、回上一步時送。"""
    out: Message = {"t": "state", **public_block(state), **_timers(state, viewer)}
    me = _me(state, viewer)
    if me is not None:
        out["me"] = _me_block(state, me)
    if viewer.kind is ViewerKind.HOST:
        out["host"] = host_block(state)
    if _ended(state):
        out["truth"] = truth_block(state, chat)
    out["chat"] = [m for m in (chat_message(c, viewer, state) for c in chat) if m is not None]
    return out


def public_messages(event: Event, state: GameState) -> list[Message]:
    """事件的公開部分，所有人內容相同（CODING_RULES P2、S3）。"""
    data = event.data
    match event.type:
        case EventType.STEP_ENTERED:
            block = public_block(state)
            keep = ("step", "step_seq", "round_no", "line_id", "speaker", "speak_queue")
            step: Message = {"t": "step", **{key: block[key] for key in keep}}
            step["public_actors"] = block["public_actors"]
            step["night_plan"] = block["night_plan"]
            step["progress"] = block["progress"]
            return [step]
        case EventType.NARRATE:
            return [
                {
                    "t": "narrate",
                    "line_id": data["line_id"],
                    "text": data["text"],
                    "speak": data["speak"],
                }
            ]
        case EventType.DEAL_ACKED | EventType.VOTE_CAST | EventType.VOTE_VOIDED:
            return [{"t": "progress", **_progress(state)}]
        case EventType.VOTES_REVEALED:
            return [{"t": "vote.reveal", "ballots": data["ballots"], "exiled": data["exiled"]}]
        case EventType.PLAYER_DIED:
            # 不含死因（SPEC A5.3）
            return [
                {
                    "t": "death",
                    "players": [{"id": data["player"], "public_role": data["public_role"]}],
                }
            ]
        case EventType.PLAYER_REVIVED:
            return [{"t": "revive", "id": data["player"]}]
        case EventType.HUNTER_RESOLVED:
            return [{"t": "hunter.shot", "hunter": data["hunter"], "target": data["target"]}]
        case EventType.PAUSED:
            return [{"t": "paused", "reason": data["reason"], "resume_at": None}]
        case EventType.RESUME_SCHEDULED:
            assert state.pause is not None
            return [{"t": "paused", "reason": state.pause.reason.value, "resume_at": data["at"]}]
        case EventType.NARRATOR_SET:
            return [{"t": "roster.narrator", "player": data["player"]}]
        case _:
            return []


def _full_state_event(event: Event) -> bool:
    return event.type in (EventType.RESUMED, EventType.ROLLED_BACK, EventType.GAME_ENDED)


def private_messages(
    event: Event, viewer: Viewer, state: GameState, chat: Sequence[Message] = ()
) -> list[Message]:
    """事件的私密部分，依觀看者加上（CODING_RULES S1）。"""
    if _full_state_event(event):
        return [build(state, viewer, chat)]
    out: list[Message] = []
    me = _me(state, viewer)
    is_host = viewer.kind is ViewerKind.HOST
    data = event.data
    if event.type is EventType.CHAT_SENT:
        msg = chat_message({**data, "ts": event.ts}, viewer, state)
        if msg is not None:
            out.append(msg)
    elif event.type in (EventType.STEP_ENTERED, EventType.TIMERS_SET, EventType.TIMED_OUT):
        if _can_see_clock(state, viewer):
            clock_msg: Message = {"t": "timers", **_timers(state, viewer)}
            clock_msg["timed_out"] = state.timed_out
            out.append(clock_msg)
        if me is not None and event.type is EventType.STEP_ENTERED:
            out.append({"t": "me", **_me_block(state, me)})
    elif event.type in (
        EventType.WOLF_PICKED,
        EventType.WOLF_PICK_CLEARED,
        EventType.WOLF_CONFIRMING,
        EventType.WOLF_DECIDED,
    ):
        if is_host or (me is not None and me.alive and is_wolf(me.role)):
            out.append({"t": "wolf.picks", **_wolf_picks(state)})
    elif event.type in (EventType.SEER_CHECKED, EventType.WITCH_ACTED, EventType.ACTOR_DONE):
        if me is not None and (me.id in state.actors or me.id in event.data.get("players", [])):
            out.append({"t": "me", **_me_block(state, me)})
    elif event.type is EventType.DISGUISE_CHANGED:
        if me is not None and me.role is Role.FACELESS:
            out.append(
                {
                    "t": "disguise",
                    **_disguise_block(state),
                    # SPEC A6：夜晚換期靜默更新，動畫延到天亮
                    "silent": rules.is_night_step(state.step),
                }
            )
    elif event.type in (EventType.VOTE_CAST, EventType.BET_SET, EventType.PLAYER_DIED):
        subject = data.get("voter") or data.get("player")
        if me is not None and me.id == subject:
            out.append({"t": "me", **_me_block(state, me)})
    elif event.type is EventType.CARD_RESHOWN and me is not None and me.id == data["player"]:
        out.append({"t": "card.reshow"})
    if is_host and event.type not in (EventType.NARRATE, EventType.CHAT_SENT):
        out.append({"t": "host.progress", **host_block(state)})
    return out


def filter_event(
    event: Event, viewer: Viewer, state: GameState, chat: Sequence[Message] = ()
) -> list[Message]:
    """某個事件送給某位觀看者的訊息（SPEC B4）。`state` 是套用該事件後的狀態。"""
    if _full_state_event(event):
        return private_messages(event, viewer, state, chat)
    return public_messages(event, state) + private_messages(event, viewer, state, chat)


def viewer_for_mode(mode: Mode, player_id: str | None, is_host: bool) -> Viewer:
    """依連線身分決定觀看者。無管理員模式的管理員＝一般玩家（SPEC A7）。"""
    if is_host and mode is Mode.GOD:
        return HOST_VIEWER
    if player_id is not None:
        return Viewer(ViewerKind.PLAYER, player_id)
    return OBSERVER_VIEWER
