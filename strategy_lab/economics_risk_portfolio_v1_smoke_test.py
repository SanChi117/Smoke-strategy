#!/usr/bin/env python3
import unittest
from strategy_lab.economics_risk_portfolio_v1 import *

class P5Tests(unittest.TestCase):
    def candidate(self, **kw):
        data=dict(candidate_id='c1',symbol='BTCUSDT',side=Side.LONG,evaluated_at='2026-01-01T00:00:00Z',entry_price=100,stop_price=99,target_price=103,atr_floor_pct=0.4,liquidity_buffer_pct=0.3,upstream_score=90,dependency_ids=('anchor1','target1'),liquidation_price=95,correlation_cluster='BTC')
        data.update(kw); return ExecutionCandidate(**data)
    def test_total_cost(self): self.assertAlmostEqual(CostModel().total_cost_pct,0.15)
    def test_minimum_move_formula(self): self.assertAlmostEqual(calculate_economics(self.candidate()).minimum_move_pct,0.6)
    def test_preferred_pass(self): self.assertEqual(evaluate_candidate(self.candidate(),AccountState(10000)).decision,AdmissionDecision.PASS)
    def test_conditional_pass_requires_score(self): self.assertEqual(evaluate_candidate(self.candidate(target_price=101.8,upstream_score=85),AccountState(10000)).decision,AdmissionDecision.CONDITIONAL_PASS)
    def test_conditional_low_score_reject(self): self.assertIn('conditional_rr_requires_score_80',evaluate_candidate(self.candidate(target_price=101.8,upstream_score=79),AccountState(10000)).reasons)
    def test_rr_below_135_reject(self): self.assertEqual(evaluate_candidate(self.candidate(target_price=101.4),AccountState(10000)).decision,AdmissionDecision.REJECT_ECONOMICS)
    def test_minimum_move_reject(self): self.assertIn('target_below_minimum_move',evaluate_candidate(self.candidate(target_price=100.5,atr_floor_pct=0.8),AccountState(10000)).reasons)
    def test_noncausal_dependency_reject(self): self.assertIn('invalid_or_noncausal_dependency',evaluate_candidate(self.candidate(dependencies_causal=False),AccountState(10000)).reasons)
    def test_cross_margin_reject(self): self.assertEqual(evaluate_candidate(self.candidate(margin_mode='cross'),AccountState(10000)).decision,AdmissionDecision.REJECT_RISK)
    def test_leverage_limit(self): self.assertIn('leverage_above_25x',evaluate_candidate(self.candidate(leverage=26),AccountState(10000)).reasons)
    def test_open_risk_limit(self): self.assertIn('total_open_risk_above_2pct',evaluate_candidate(self.candidate(),AccountState(10000,open_risk_pct=1.75)).reasons)
    def test_liquidation_safety(self): self.assertIn('liquidation_distance_unsafe',evaluate_candidate(self.candidate(liquidation_price=98.5),AccountState(10000)).reasons)
    def test_missing_liquidation(self): self.assertIn('missing_liquidation_price',evaluate_candidate(self.candidate(liquidation_price=None),AccountState(10000)).reasons)
    def test_risk_sizing(self):
        r=evaluate_candidate(self.candidate(),AccountState(10000)); self.assertAlmostEqual(r.position.risk_amount,50); self.assertAlmostEqual(r.position.notional,5000)
    def test_deterministic_ranking_cluster_first(self):
        a=evaluate_candidate(self.candidate(candidate_id='a',correlation_cluster='L1'),AccountState(10000))
        b=evaluate_candidate(self.candidate(candidate_id='b',correlation_cluster='L1',target_price=104),AccountState(10000))
        c=evaluate_candidate(self.candidate(candidate_id='c',correlation_cluster='L2'),AccountState(10000))
        ranked=rank_simultaneous_candidates((a,b,c),AccountState(10000),upstream_scores={'a':90,'b':95,'c':80})
        self.assertEqual([x.candidate_id for x in ranked[:2]],['b','c'])
        self.assertEqual([x.portfolio_rank for x in ranked],list(range(1,len(ranked)+1)))
    def test_no_outcome_export(self):
        payload=result_to_no_pnl_dict(evaluate_candidate(self.candidate(),AccountState(10000))); self.assertEqual(payload['decision'],'PASS'); self.assertNotIn('pnl',str(payload).lower())
    def test_prices_never_mutated(self):
        c=self.candidate(); evaluate_candidate(c,AccountState(10000)); self.assertEqual((c.entry_price,c.stop_price,c.target_price),(100,99,103))

if __name__=='__main__': unittest.main()
