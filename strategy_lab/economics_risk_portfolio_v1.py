#!/usr/bin/env python3
"""SMOKE CORE 1.0 P5: causal economics, risk and portfolio admission engine."""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Sequence

class Side(str, Enum):
    LONG='LONG'; SHORT='SHORT'
class AdmissionDecision(str, Enum):
    PASS='PASS'; CONDITIONAL_PASS='CONDITIONAL_PASS'; REJECT_ECONOMICS='REJECT_ECONOMICS'; REJECT_RISK='REJECT_RISK'

@dataclass(frozen=True)
class CostModel:
    entry_fee_pct: float=0.04
    exit_fee_pct: float=0.04
    entry_slippage_pct: float=0.02
    exit_slippage_pct: float=0.02
    expected_funding_pct: float=0.01
    cost_buffer_pct: float=0.02
    def __post_init__(self):
        if any(v < 0 for v in asdict(self).values()): raise ValueError('cost components must be non-negative')
    @property
    def total_cost_pct(self): return round(sum(asdict(self).values()),10)

@dataclass(frozen=True)
class RiskLimits:
    risk_per_position_pct: float=0.5
    max_total_open_risk_pct: float=2.0
    default_leverage: float=20.0
    max_leverage: float=25.0
    max_margin_per_position_pct: float=10.0
    max_total_margin_pct: float=25.0
    max_total_notional_multiple: float=2.5
    min_net_rr: float=1.35
    preferred_net_rr: float=1.70
    conditional_score_min: float=80.0
    isolated_margin_required: bool=True
    def __post_init__(self):
        if not 0 < self.risk_per_position_pct <= self.max_total_open_risk_pct: raise ValueError('invalid risk limits')
        if not 0 < self.default_leverage <= self.max_leverage: raise ValueError('invalid leverage limits')
        if not 0 < self.min_net_rr < self.preferred_net_rr: raise ValueError('invalid rr limits')

@dataclass(frozen=True)
class ExecutionCandidate:
    candidate_id: str; symbol: str; side: Side; evaluated_at: str
    entry_price: float; stop_price: float; target_price: float
    atr_floor_pct: float; liquidity_buffer_pct: float; upstream_score: float
    dependency_ids: tuple[str,...]; dependencies_causal: bool=True
    leverage: float|None=None; margin_mode: str='isolated'; liquidation_price: float|None=None
    correlation_cluster: str='UNCLASSIFIED'
    def __post_init__(self):
        if min(self.entry_price,self.stop_price,self.target_price)<=0: raise ValueError('prices must be positive')
        if self.side==Side.LONG and not self.stop_price<self.entry_price<self.target_price: raise ValueError('invalid LONG geometry')
        if self.side==Side.SHORT and not self.target_price<self.entry_price<self.stop_price: raise ValueError('invalid SHORT geometry')
        if min(self.atr_floor_pct,self.liquidity_buffer_pct)<0: raise ValueError('floors must be non-negative')
        if not 0<=self.upstream_score<=100: raise ValueError('upstream_score must be in [0,100]')

@dataclass(frozen=True)
class AccountState:
    equity: float; open_risk_pct: float=0.0; used_margin_pct: float=0.0; total_notional_multiple: float=0.0
    cluster_risk_pct: Mapping[str,float]|None=None
    def __post_init__(self):
        if self.equity<=0: raise ValueError('equity must be positive')
        if min(self.open_risk_pct,self.used_margin_pct,self.total_notional_multiple)<0: raise ValueError('exposures must be non-negative')

@dataclass(frozen=True)
class EconomicsBreakdown:
    total_cost_pct: float; minimum_move_pct: float; target_move_pct: float; stop_move_pct: float
    gross_reward_pct: float; gross_loss_pct: float; effective_net_reward_pct: float; effective_net_loss_pct: float; net_rr: float

@dataclass(frozen=True)
class PositionPlan:
    leverage: float; risk_amount: float; stop_distance_pct: float; notional: float; margin: float
    margin_pct_equity: float; notional_multiple_equity: float; liquidation_distance_pct: float|None
    liquidation_required_distance_pct: float

@dataclass(frozen=True)
class AdmissionResult:
    evaluation_id: str; candidate_id: str; dependency_ids: tuple[str,...]; decision: AdmissionDecision
    economics: EconomicsBreakdown; position: PositionPlan; reasons: tuple[str,...]; correlation_cluster: str
    portfolio_rank: int|None=None

FORBIDDEN_KEY_FRAGMENTS=('pnl','future_return','trade_outcome','tp_result','sl_result','mfe','mae','profit_factor','net_return','drawdown','exit_price','exit_reason')
def _stable_id(prefix,*parts):
    return f"{prefix}_{sha256('|'.join(map(str,parts)).encode()).hexdigest()[:20]}"
def _move_pct(c):
    e=c.entry_price
    return (((c.target_price-e)/e*100,(e-c.stop_price)/e*100) if c.side==Side.LONG else ((e-c.target_price)/e*100,(c.stop_price-e)/e*100))
def _liquidation_distance_pct(c):
    if c.liquidation_price is None: return None
    e=c.entry_price
    return max(0.0,((e-c.liquidation_price)/e*100) if c.side==Side.LONG else ((c.liquidation_price-e)/e*100))

def calculate_economics(candidate,cost_model=None):
    costs=cost_model or CostModel(); target,stop=_move_pct(candidate); total=costs.total_cost_pct
    minimum=max(4*total,candidate.atr_floor_pct,candidate.liquidity_buffer_pct)
    net_reward=target-total; net_loss=stop+total; net_rr=net_reward/net_loss if net_loss>0 else 0.0
    return EconomicsBreakdown(*[round(x,10) for x in (total,minimum,target,stop,target,stop,net_reward,net_loss,net_rr)])

def build_position_plan(candidate,account,economics,costs=None,limits=None):
    costs=costs or CostModel(); limits=limits or RiskLimits(); leverage=candidate.leverage or limits.default_leverage
    risk_amount=account.equity*limits.risk_per_position_pct/100; notional=risk_amount/max(economics.stop_move_pct/100,1e-12); margin=notional/max(leverage,1e-12)
    liq=_liquidation_distance_pct(candidate); required=2*economics.stop_move_pct+costs.cost_buffer_pct
    return PositionPlan(round(leverage,10),round(risk_amount,10),economics.stop_move_pct,round(notional,10),round(margin,10),round(margin/account.equity*100,10),round(notional/account.equity,10),round(liq,10) if liq is not None else None,round(required,10))

def evaluate_candidate(candidate,account,cost_model=None,limits=None):
    costs=cost_model or CostModel(); limits=limits or RiskLimits(); economics=calculate_economics(candidate,costs); position=build_position_plan(candidate,account,economics,costs,limits)
    er=[]; rr=[]
    if not candidate.dependency_ids or not candidate.dependencies_causal: er.append('invalid_or_noncausal_dependency')
    if economics.target_move_pct<=2*economics.total_cost_pct: er.append('target_not_above_two_times_cost')
    if economics.target_move_pct<economics.minimum_move_pct: er.append('target_below_minimum_move')
    if economics.effective_net_reward_pct<=0: er.append('non_positive_net_reward')
    if economics.net_rr<limits.min_net_rr: er.append('net_rr_below_1_35')
    conditional=limits.min_net_rr<=economics.net_rr<limits.preferred_net_rr
    if conditional and candidate.upstream_score<limits.conditional_score_min: er.append('conditional_rr_requires_score_80')
    if limits.isolated_margin_required and candidate.margin_mode.lower()!='isolated': rr.append('isolated_margin_required')
    if position.leverage>limits.max_leverage: rr.append('leverage_above_25x')
    if position.leverage<=0: rr.append('invalid_leverage')
    if position.margin_pct_equity>limits.max_margin_per_position_pct: rr.append('margin_per_position_above_10pct')
    if account.open_risk_pct+limits.risk_per_position_pct>limits.max_total_open_risk_pct: rr.append('total_open_risk_above_2pct')
    if account.used_margin_pct+position.margin_pct_equity>limits.max_total_margin_pct: rr.append('total_margin_above_25pct')
    if account.total_notional_multiple+position.notional_multiple_equity>limits.max_total_notional_multiple: rr.append('total_notional_above_2_5x')
    if position.liquidation_distance_pct is None: rr.append('missing_liquidation_price')
    elif position.liquidation_distance_pct<position.liquidation_required_distance_pct: rr.append('liquidation_distance_unsafe')
    if er: decision=AdmissionDecision.REJECT_ECONOMICS; reasons=er+rr
    elif rr: decision=AdmissionDecision.REJECT_RISK; reasons=rr
    elif conditional: decision=AdmissionDecision.CONDITIONAL_PASS; reasons=['conditional_net_rr_with_score_80']
    else: decision=AdmissionDecision.PASS; reasons=['preferred_net_rr_and_risk_pass']
    return AdmissionResult(_stable_id('econ',candidate.candidate_id,candidate.evaluated_at,economics.net_rr,position.notional),candidate.candidate_id,tuple(candidate.dependency_ids),decision,economics,position,tuple(reasons),candidate.correlation_cluster)

def rank_simultaneous_candidates(results,account,limits=None,upstream_scores=None):
    limits=limits or RiskLimits(); scores=upstream_scores or {}; admissible=[r for r in results if r.decision in (AdmissionDecision.PASS,AdmissionDecision.CONDITIONAL_PASS)]
    ordered=sorted(admissible,key=lambda r:(-float(scores.get(r.candidate_id,0)),-r.economics.net_rr,r.position.margin_pct_equity,r.candidate_id))
    selected=[]; deferred=[]; clusters=set(); risk=account.open_risk_pct; margin=account.used_margin_pct; notional=account.total_notional_multiple
    def fits(r): return risk+limits.risk_per_position_pct<=limits.max_total_open_risk_pct and margin+r.position.margin_pct_equity<=limits.max_total_margin_pct and notional+r.position.notional_multiple_equity<=limits.max_total_notional_multiple
    for r in ordered:
        if r.correlation_cluster in clusters: deferred.append(r); continue
        if not fits(r): continue
        selected.append(r); clusters.add(r.correlation_cluster); risk+=limits.risk_per_position_pct; margin+=r.position.margin_pct_equity; notional+=r.position.notional_multiple_equity
    for r in deferred:
        if not fits(r): continue
        selected.append(r); risk+=limits.risk_per_position_pct; margin+=r.position.margin_pct_equity; notional+=r.position.notional_multiple_equity
    return tuple(replace(r,portfolio_rank=i+1) for i,r in enumerate(selected))

def result_to_no_pnl_dict(result):
    payload=asdict(result); payload['decision']=result.decision.value; text=str(payload).lower()
    for fragment in FORBIDDEN_KEY_FRAGMENTS:
        if fragment in text: raise ValueError(f'forbidden outcome field fragment: {fragment}')
    return payload
