"""機器人玩家（CODING_RULES D1、DEV_PLAN P2）：無網路無畫面跑完整局。

機器人只看 `views.build` 給它的資料，不能偷看狀態；能跑完就證明前端拿得到足夠的資訊。

用法：python -m server.dev.bots --players 10 --mode auto --seed 42
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from server.clock import FakeClock
from server.engine import LINE_STEPS, Engine
from server.enums import Action, Channel, Mode, PauseReason, Role, Step, Winner
from server.errors import GameError
from server.events import Event, EventType, replay
from server.modes import Actor
from server.rng import GameRng
from server.roles import is_wolf
from server.rules import public_role, role_is_public
from server.views import HOST_VIEWER, OBSERVER_VIEWER, Viewer, ViewerKind, build, filter_event

TICK_SECONDS = 0.25
MAX_TICKS = 2_000_000
ROUND_LIMIT = 40
_ROLE_TOKENS = re.compile(r'"(wolf|faceless|villager|seer|witch|hunter)"')
ADMIN = Actor(is_admin=True)
HOST = Actor(is_admin=True, is_host=True)


class LeakFound(Exception):
    """保密測試失敗（CODING_RULES T4）。"""


@dataclass
class RunResult:
    seed: int
    players: int
    mode: Mode
    winner: Winner
    rounds: int
    events: list[Event] = field(default_factory=list)
    messages_checked: int = 0


def allowed_tokens(engine: Engine, viewer: Viewer) -> set[str] | None:
    """這位觀看者此刻可以看到哪些角色代號（SPEC A7）；None 表示全部都能看。"""
    state = engine.state
    if viewer.kind is ViewerKind.HOST or state.step is Step.END:
        return None
    allowed = {public_role(p.role).value for p in state.players if role_is_public(state, p)}
    if state.step is Step.HUNTER or state.hunter_shots:
        allowed.add(Role.HUNTER.value)  # 旁白念了「獵人」、開槍即公開
    if viewer.player_id is not None:
        me = state.player(viewer.player_id)
        allowed.add(me.role.value)
        if is_wolf(me.role):
            allowed.add(Role.WOLF.value)
    return allowed


def scan_for_leaks(payload: Any, engine: Engine, viewer: Viewer) -> None:
    """全文搜尋不該出現的角色代號與死因（CODING_RULES T4）。"""
    allowed = allowed_tokens(engine, viewer)
    if allowed is None:
        return
    text = json.dumps(payload, ensure_ascii=False)
    leaked = set(_ROLE_TOKENS.findall(text)) - allowed
    if leaked:
        raise LeakFound(f"step={engine.state.step} viewer={viewer} leaked={sorted(leaked)}")


def scan_disguise_leak(event: Event, payload: Any, viewer: Viewer, ended: bool) -> None:
    """假扮訊息送給他人時，資料裡不能有真實發言者（SPEC A7）。"""
    if event.type is not EventType.CHAT_SENT:
        return
    if event.data["disguise_period"] is None and not event.data["is_wolf_mask"]:
        return
    if viewer.kind is ViewerKind.HOST or ended or viewer.player_id == event.data["real_author"]:
        return
    if event.data["real_author"] in json.dumps(payload):
        raise LeakFound(f"real author leaked to {viewer}")


class BotBrain:
    """機器人的決策。只看 `views.build` 給的資料，靠 `send` 送意圖（DEV_PLAN P2）。"""

    def __init__(
        self,
        rng: GameRng,
        now: Callable[[], float],
        send: Callable[[Actor, Action, dict[str, Any] | None], bool],
        speak_rate: float = 0.3,
        chat_rate: float = 0.01,
    ) -> None:
        self.rng = rng
        self.now = now
        self._send = send
        self.speak_rate = speak_rate
        self.chat_rate = chat_rate

    def send(self, actor: Actor, action: Action, payload: dict[str, Any] | None = None) -> bool:
        return self._send(actor, action, payload)

    def _pick(self, items: list[str]) -> str:
        return self.rng.choice(sorted(items))

    def _roll(self, rate: float) -> bool:
        return self.rng.randrange(1000) < rate * 1000

    def turn(self, player_id: str, view: dict[str, Any]) -> None:
        """看自己的視圖，決定要不要行動。"""
        me = view["me"]
        actor = Actor(player_id=player_id)
        step = Step(view["step"])
        if not me["alive"] and me["can_bet"] and self._roll(0.02):
            self._bet(actor, view)
        if self._roll(self.chat_rate):
            self._chat(actor, view, me)
        if not me["is_actor"] or (me["done"] and step is not Step.VOTE):
            return
        opens_at = view.get("opens_at")
        if opens_at is not None and self.now() < opens_at:
            return
        self._step_action(actor, step, me, view)

    def _step_action(
        self, actor: Actor, step: Step, me: dict[str, Any], view: dict[str, Any]
    ) -> None:
        targets: list[str] = me.get("eligible_targets", [])
        if step is Step.DEAL:
            self.send(actor, Action.DEAL_ACK)
        elif step is Step.WOLF:
            self._wolf(actor, me, targets)
        elif step is Step.SEER:
            self._seer(actor, me, targets, view)
        elif step is Step.WITCH:
            self._witch(actor, me, targets)
        elif step is Step.HUNTER:
            target = self._pick(targets) if targets and self._roll(0.8) else None
            self.send(actor, Action.HUNTER_SHOOT, {"target": target})
        elif step in (Step.LAST_WORDS, Step.DAY_SPEAK):
            if self._roll(self.speak_rate):
                self.send(actor, Action.SPEAK_END)
        elif step is Step.VOTE:
            self._vote(actor, me, targets)

    def _wolf(self, actor: Actor, me: dict[str, Any], targets: list[str]) -> None:
        status = me["wolf_pack"]
        if status.get("decided") or status.get("confirming_until") is not None:
            return
        picks = status.get("picks", {})
        if me["id"] in picks and self._roll(0.7):
            return
        # 跟著同伴選的機率高，讓一致與不一致兩條路都走得到
        chosen = [t for t in picks.values() if t is not None]
        if chosen and self._roll(0.7):
            self.send(actor, Action.WOLF_PICK, {"target": chosen[0]})
        elif self._roll(0.1):
            self.send(actor, Action.WOLF_PICK, {"target": None})
        elif self._roll(0.05) and me["id"] in picks:
            self.send(actor, Action.WOLF_PICK, {"clear": True})
        elif targets:
            self.send(actor, Action.WOLF_PICK, {"target": self._pick(targets)})

    def _seer(
        self, actor: Actor, me: dict[str, Any], targets: list[str], view: dict[str, Any]
    ) -> None:
        round_no = view["round_no"]
        checks = me["seer_info"]["checks"]
        if any(c["round_no"] == round_no for c in checks):
            self.send(actor, Action.SEER_OK)
        elif targets:
            self.send(actor, Action.SEER_CHECK, {"target": self._pick(targets)})

    def _witch(self, actor: Actor, me: dict[str, Any], targets: list[str]) -> None:
        info = me["witch_info"]
        if info["can_save"] and self._roll(0.5):
            self.send(actor, Action.WITCH_ACT, {"save": True})
        elif info["can_poison"] and targets and self._roll(0.3):
            self.send(actor, Action.WITCH_ACT, {"poison": self._pick(targets)})
        else:
            self.send(actor, Action.WITCH_ACT, {})

    def _vote(self, actor: Actor, me: dict[str, Any], targets: list[str]) -> None:
        mine = me.get("my_vote")
        if mine is not None and (not mine["can_change"] or not self._roll(0.02)):
            return
        target = self._pick(targets) if targets and self._roll(0.9) else None
        self.send(actor, Action.VOTE_CAST, {"target": target})

    def _bet(self, actor: Actor, view: dict[str, Any]) -> None:
        others = [p["id"] for p in view["players"] if p["id"] != view["me"]["id"]]
        self.send(actor, Action.BET_SET, {"wolves": [self._pick(others)], "faceless": None})

    def _chat(self, actor: Actor, view: dict[str, Any], me: dict[str, Any]) -> None:
        if me.get("can_disguise") and self._roll(0.5):
            self.send(
                actor,
                Action.CHAT_SEND,
                {"channel": Channel.PUBLIC, "as": "disguise", "kind": "text", "content": "假扮"},
            )
            return
        if me.get("can_wolf_mask") and self._roll(0.3):
            self.send(
                actor,
                Action.CHAT_SEND,
                {"channel": Channel.PUBLIC, "as": "wolf", "kind": "text", "content": "嗷嗚"},
            )
            return
        channel = Channel.WOLF if "wolf_pack" in me and self._roll(0.5) else Channel.PUBLIC
        self.send(actor, Action.CHAT_SEND, {"channel": channel, "kind": "text", "content": "你好"})


class Simulation:
    """一局模擬。`chaos` 開啟時會隨機踢人、暫停、回上一步，用來壓測引擎。"""

    def __init__(
        self,
        players: int,
        mode: Mode,
        seed: int,
        chaos: bool = False,
        leak_check: bool = True,
        idle_rate: float = 0.1,
        on_event: Callable[[Event], None] | None = None,
    ) -> None:
        self.clock = FakeClock()
        self.choice_rng = GameRng(seed * 7 + 1)
        self.chaos = chaos
        self.leak_check = leak_check
        self.idle_rate = idle_rate
        self.on_event = on_event
        self.seed = seed
        self.mode = mode
        self.messages_checked = 0
        self.brain = BotBrain(self.choice_rng, self.clock.now, self._try)
        ids = [(f"p{i:02d}", f"玩{i:02d}") for i in range(1, players + 1)]
        narrator = None if mode is Mode.GOD else ids[0][0]
        self.engine = Engine.create(ids, mode, {}, self.clock, GameRng(seed), narrator_id=narrator)
        self.viewers = [Viewer(ViewerKind.PLAYER, pid) for pid, _ in ids]
        self.viewers += [OBSERVER_VIEWER] + ([HOST_VIEWER] if mode is Mode.GOD else [])
        self._observe(self.engine.log[1:])

    # ---- 觀察 ----

    def _observe(self, events: Iterable[Event]) -> None:
        for event in events:
            if self.on_event is not None:
                self.on_event(event)
            if self.leak_check:
                for viewer in self.viewers:
                    payload = filter_event(event, viewer, self.engine.state)
                    self.messages_checked += len(payload)
                    scan_for_leaks(payload, self.engine, viewer)
                    scan_disguise_leak(event, payload, viewer, self.engine.state.step is Step.END)

    def _try(self, actor: Actor, action: Action, payload: dict[str, Any] | None = None) -> bool:
        """送意圖；被拒絕是正常的（例如別人先推進了），不算失敗。"""
        step_seq = self.engine.state.step_seq
        try:
            self._observe(self.engine.handle(actor, action, payload or {}, step_seq))
        except GameError:
            return False
        return True

    # ---- 主迴圈 ----

    def run(self) -> RunResult:
        for _ in range(MAX_TICKS):
            state = self.engine.state
            if state.step is Step.END:
                return self._result()
            if state.round_no > ROUND_LIMIT:
                # SPEC A5.6：無回合上限，由管理員中途結束
                self._try(self._admin(), Action.ADMIN_END)
                continue
            self._bots_act()
            if self.chaos:
                self._chaos()
            if self.mode is Mode.GOD:
                self._host_acts()
            self.clock.advance(TICK_SECONDS)
            self._observe(self.engine.tick())
        raise TimeoutError(f"game did not end, seed={self.seed}")

    def _result(self) -> RunResult:
        winner = self.engine.state.winner
        assert winner is not None
        return RunResult(
            seed=self.seed,
            players=len(self.engine.state.players),
            mode=self.mode,
            winner=winner,
            rounds=self.engine.state.round_no,
            events=self.engine.log,
            messages_checked=self.messages_checked,
        )

    def _admin(self) -> Actor:
        return HOST if self.mode is Mode.GOD else ADMIN

    def _pick(self, items: list[str]) -> str:
        return self.choice_rng.choice(sorted(items))

    def _roll(self, rate: float) -> bool:
        return self.choice_rng.randrange(1000) < rate * 1000

    # ---- 玩家機器人：只看自己的視圖 ----

    def _bots_act(self) -> None:
        state = self.engine.state
        if state.pause is not None:
            return
        for viewer in self.viewers:
            if viewer.player_id is None or self._roll(self.idle_rate):
                continue
            view = build(self.engine.state, viewer)
            self._bot_turn(viewer.player_id, view)
            if self.engine.state.step is Step.END:
                return

    def _bot_turn(self, player_id: str, view: dict[str, Any]) -> None:
        self.brain.turn(player_id, view)

    # ---- 主持人機器人 ----

    def _host_acts(self) -> None:
        engine = self.engine
        state = engine.state
        if state.pause is not None or state.step is Step.END:
            return
        now = self.clock.now()
        if not engine.is_step_complete(now):
            # 偶爾不等人就按下一句（SPEC A8.2 主持人可略過未完成者）
            if self._roll(0.0005):
                self._try(HOST, Action.HOST_NEXT)
            return
        next_step = engine.next_step()
        if next_step is Step.END or engine.policy.should_advance(next_step):
            return
        line = next(line for line, step in LINE_STEPS.items() if step is next_step)
        self._try(HOST, Action.HOST_LINE, {"line_id": line, "speak": self._roll(0.8)})

    # ---- 壓力測試 ----

    def _chaos(self) -> None:
        state = self.engine.state
        admin = self._admin()
        if state.pause is not None:
            if state.pause.resume_at is None and self._roll(0.01):
                self._try(admin, Action.ADMIN_RESUME)
            return
        if self._roll(0.0005):
            alive = [p.id for p in state.players if p.alive]
            if alive:
                self._try(admin, Action.ADMIN_KICK, {"player": self._pick(alive)})
        elif self._roll(0.001):
            self._try(admin, Action.ADMIN_PAUSE)
        elif self._roll(0.0005):
            self._observe(self.engine.system_pause(PauseReason.PRESENCE))
        elif self.mode is Mode.GOD and self._roll(0.0005):
            self._try(HOST, Action.HOST_ROLLBACK)
        elif self.mode is Mode.GOD and self._roll(0.0005):
            self._try(HOST, Action.HOST_EXTEND, {"s": 30})
        elif self.mode is Mode.GOD and self._roll(0.0003):
            target = self._pick([p.id for p in state.players])
            self._try(HOST, Action.HOST_SET_ALIVE, {"player": target, "alive": False})


def run_game(
    players: int, mode: Mode, seed: int, chaos: bool = False, leak_check: bool = True
) -> RunResult:
    """跑一局並回傳結果。"""
    return Simulation(players, mode, seed, chaos=chaos, leak_check=leak_check).run()


def assert_replay_matches(result: RunResult, final_state_json: dict[str, Any]) -> None:
    """重播事件必須得到相同狀態（CODING_RULES T9）。"""
    rebuilt = replay(result.events).model_dump(mode="json")
    if rebuilt != final_state_json:
        raise AssertionError(f"replay mismatch, seed={result.seed}")


def main() -> None:
    parser = argparse.ArgumentParser(description="機器人跑一局")
    parser.add_argument("--players", type=int, default=10)
    parser.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.AUTO.value)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--chaos", action="store_true")
    args = parser.parse_args()
    result = run_game(args.players, Mode(args.mode), args.seed, chaos=args.chaos)
    counts = Counter(e.type.value for e in result.events)
    print(
        f"seed={result.seed} players={result.players} mode={result.mode.value} "
        f"winner={result.winner.value} rounds={result.rounds}"
    )
    print(f"events={len(result.events)} messages_checked={result.messages_checked}")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
