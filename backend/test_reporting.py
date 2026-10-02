from copy import deepcopy
from datetime import datetime,timedelta,timezone
import pytest
from app.savings import summary, comparison_for
from app.performance import summary as performance


def shipment(sid='S1', **changes):
    start=datetime.now(timezone.utc)-timedelta(days=2)
    eta=start+timedelta(hours=5)
    p={'quote_id':'q1','path':['A','B'],'revision':1,'depart_at':start.isoformat(),
       'eta':eta.isoformat(),'total_minutes':300,'cost':{'transport_eur':400},
       'comparison':{'baseline':'Same-pass direct route','money_saved_eur':100,'fuel_saved_l':10,'minutes_saved':60}}
    return {'id':sid,'route':['A','B'],'data_kind':'user','status':'SCHEDULED','approved_at':start.isoformat(),
            'accepted_plan':p,**changes}


def outcome(sid='S1', **changes):
    s=shipment(sid,**changes)
    p=s['accepted_plan']
    s['actual']={'accepted_quote_id':'q1','actual_departure':p['depart_at'],
                 'actual_arrival':(datetime.fromisoformat(p['eta'])+timedelta(minutes=15)).isoformat(),
                 'actual_cost_eur':420,'on_time':True}
    return s


def test_empty_is_zero_estimates_and_no_invented_measurements():
    s=summary([]);p=performance([])
    assert s['per_shipment']==[] and s['total']['optimized']==0
    assert s['total']['economic_benefit_eur']==0
    assert p['samples']==0 and p['status']=='INSUFFICIENT_DATA'
    assert p['on_time_pct'] is None and p['arrival_mae_minutes'] is None


def test_demo_unapproved_and_held_plans_never_inflate_operational_totals():
    approved=shipment()
    demo=shipment('DEMO',data_kind='demo')
    proposal=shipment('PROPOSAL',approved_at=None)
    hold=shipment('HOLD',status='ON HOLD',hold={'reason':'Weather'})
    s=summary([approved,demo,proposal,hold])
    assert s['total']['optimized']==1 and s['total']['money_eur']==100
    assert s['excluded_count']==2 and s['demo_excluded_count']==1
    assert all(r['id']!='DEMO' for r in s['per_shipment'])
    d=summary([approved,demo],scope='demo')
    assert [r['id'] for r in d['per_shipment']]==['DEMO']
    assert d['scope']=='demo' and d['per_shipment'][0]['data_kind']=='demo'


def test_exposure_and_reroute_values_are_not_added_twice():
    s=shipment(disruption_savings={'approved_quote_id':'q1','minutes_avoided':120,'cost_delta_eur':20,'exposure_avoided_eur':180000})
    totals=summary([s])['total']
    assert totals['economic_benefit_eur']==150  # 100 transport + 50 time value only
    assert totals['disruption_eur']==80 and totals['exposure_avoided_eur']==180000


def test_signed_losses_and_missing_baseline_are_preserved():
    s=shipment();s['accepted_plan']['comparison']['money_saved_eur']=-100
    s['accepted_plan']['comparison']['minutes_saved']=-60
    legacy=shipment('LEGACY');legacy['accepted_plan'].pop('comparison')
    result=summary([s,legacy])
    assert result['total']['economic_benefit_eur']==-150
    assert result['legacy_count']==1 and result['total']['optimized']==1


def test_stale_reroute_attribution_is_excluded():
    s=shipment(disruption_savings={'approved_quote_id':'old','minutes_avoided':100,'exposure_avoided_eur':99999})
    assert summary([s])['total']['disruption_eur']==0
    assert summary([s])['total']['exposure_avoided_eur']==0


def test_provenance_and_different_quote_baselines():
    s=shipment(approval_reason='Avoid the storm corridor')
    assert summary([s])['per_shipment'][0]['evidence']['manager_reason']=='Avoid the storm corridor'
    s['accepted_plan'].pop('comparison')
    s['options']=[{**deepcopy(s['accepted_plan']),'quote_id':'different'}]
    assert comparison_for(s)[0] is None


def test_actuals_have_sample_threshold_and_no_false_zero_metrics():
    one=performance([outcome()])
    assert one['samples']==1 and one['arrival_mae_minutes'] is None
    assert one['outcomes'][0]['arrival_error_minutes']==15
    actual=performance([outcome(str(i)) for i in range(5)])
    assert actual['status']=='MEASURED' and actual['samples']==5
    assert actual['arrival_mae_minutes']==15 and actual['cost_error_eur']==20
    assert actual['on_time_pct']==100


def test_actuals_exclude_demo_unapproved_mismatched_and_future_reports():
    demo=outcome('D',data_kind='demo')
    unapproved=outcome('U',approved_at=None)
    old=outcome('O');old['actual']['accepted_quote_id']='old'
    future=outcome('F');future['actual']['actual_arrival']=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    p=performance([outcome(),demo,unapproved,old,future])
    assert p['samples']==1 and p['excluded_records']==4


def test_actual_deadline_percent_requires_five_known_deadlines():
    items=[outcome(str(i)) for i in range(5)]
    items[0]['actual']['on_time']=None
    p=performance(items)
    assert p['status']=='MEASURED' and p['deadline_samples']==4 and p['on_time_pct'] is None
