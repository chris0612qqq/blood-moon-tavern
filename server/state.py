"""遊戲狀態結構。只有 `events.apply` 可以改它（CODING_RULES G1）。"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

from server.enums import (
    DayContext,
    DeathCause,
    DisguiseEnd,
    Mode,
    PauseReason,
    Role,
    Step,
    Winner,
)

SCHEMA_VERSION: Final = 2


class PlayerState(BaseModel):
    id: str
    name: str
    # 旁白念的名字（SPEC v4.40）；舊存檔沒有這欄就念顯示名字
    spoken: str = ""
    seat: int
    role: Role
    alive: bool = True
    death_cause: DeathCause | None = None
    death_round: int | None = None
    acked: bool = False

    def voice(self) -> str:
        """旁白要念的名字。"""
        return self.spoken or self.name


class DisguisePeriod(BaseModel):
    target_id: str
    from_round: int
    to_round: int | None = None
    ended_reason: DisguiseEnd | None = None


class DisguiseState(BaseModel):
    faceless_id: str
    target_id: str | None = None
    rounds_left: int = 0
    previous_target: str | None = None
    periods: list[DisguisePeriod] = Field(default_factory=list)


class NightRecord(BaseModel):
    round_no: int
    # 守衛（SPEC v4.42）：舊存檔沒有這兩欄，預設＝沒守
    guard_acted: bool = False
    guard_target: str | None = None
    wolf_picks: dict[str, str | None] = Field(default_factory=dict)
    wolf_decided: bool = False
    wolf_target: str | None = None
    seer_target: str | None = None
    seer_is_wolf: bool | None = None
    witch_acted: bool = False
    witch_saved: bool = False
    witch_poison: str | None = None


class VoteRound(BaseModel):
    round_no: int
    ballots: dict[str, str | None] = Field(default_factory=dict)
    changed: list[str] = Field(default_factory=list)
    exiled: str | None = None
    revealed: bool = False
    # 第一輪只留結果（SPEC A5.4）：誰投誰不留在狀態裡，紀錄和看真相都只有第二輪
    nominees: list[str] | None = None
    suspect_counts: dict[str, int] = Field(default_factory=dict)
    # 第一輪就決定了（被投的少於 3 人）：沒有申述和第二輪
    direct: bool = False


class HunterShot(BaseModel):
    round_no: int
    hunter: str
    target: str | None = None


class WolfSchedule(BaseModel):
    """狼人定時電子音（SPEC v4.24）：時間是現實時間（epoch 秒），只有本人看得到。"""

    slot: int
    due: float
    text: str


class Timers(BaseModel):
    """目前步驟的時間點。全部用同一個時鐘；暫停時換算成剩餘秒數（CODING_RULES L5）。"""

    opens_at: float | None = None
    deadline: float | None = None
    min_until: float | None = None
    confirm_until: float | None = None
    grace_until: float | None = None


class PauseState(BaseModel):
    reason: PauseReason
    remaining: dict[str, float] = Field(default_factory=dict)
    resume_at: float | None = None


class GameState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    mode: Mode
    players: list[PlayerState]
    settings: dict[str, int] = Field(default_factory=dict)
    narrator_id: str | None = None

    step: Step = Step.DEAL
    step_seq: int = 0
    round_no: int = 0
    timers: Timers = Field(default_factory=Timers)
    actors: list[str] = Field(default_factory=list)
    done: list[str] = Field(default_factory=list)
    line_id: str | None = None
    timed_out: bool = False
    announced: bool = False
    pause: PauseState | None = None

    witch_antidote_used: bool = False
    witch_poison_used: bool = False
    nights: list[NightRecord] = Field(default_factory=list)
    votes: list[VoteRound] = Field(default_factory=list)
    disguise: DisguiseState | None = None
    wolf_schedules: dict[str, list[WolfSchedule]] = Field(default_factory=dict)

    day_context: DayContext | None = None
    dawn_deaths: list[str] = Field(default_factory=list)
    hunter_pending: str | None = None
    hunter_shot_done: bool = False
    hunter_shots: list[HunterShot] = Field(default_factory=list)
    last_speak_start: str | None = None
    pending_last_words: list[str] = Field(default_factory=list)
    last_words_sent: list[str] = Field(default_factory=list)
    speak_queue: list[str] = Field(default_factory=list)
    current_speaker: str | None = None

    winner: Winner | None = None

    def player(self, player_id: str) -> PlayerState:
        """依 id 取玩家；不存在時拋 KeyError。"""
        for candidate in self.players:
            if candidate.id == player_id:
                return candidate
        raise KeyError(player_id)

    def has_player(self, player_id: str) -> bool:
        return any(p.id == player_id for p in self.players)

    def night(self) -> NightRecord:
        """本回合的夜晚紀錄。"""
        return self.nights[-1]

    def vote_round(self) -> VoteRound:
        """本回合的投票紀錄。"""
        return self.votes[-1]
