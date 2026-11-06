"""План перевозчика, фактический счёт и аудируемые корректировки — отдельно."""
from decimal import Decimal
import pandas as pd


def apply_carrier_expenses(frame, evidence):
    out=frame.copy()
    if out.empty:
        return out
    evidence={int(row['item_id']):row for row in evidence}
    for index,row in out.iterrows():
        item=evidence.get(int(row['item_id']),{})
        q=Decimal(str(row.get('quantity') or 1))
        snapshot=row.get('pricing_snapshot')
        comps={c['code']:Decimal(str(c['amount'])) for c in snapshot.get('components',[])} if isinstance(snapshot,dict) else {}
        metadata=(snapshot.get('decision') or {}).get('metadata',{}).get('carrier_delivery',{}) if isinstance(snapshot,dict) else {}
        old_plan=Decimal(str(row.get('custom_delivery_fee_total') or 0))
        planned=(comps.get('carrier_delivery',Decimal(0))+comps.get('carrier_insurance',Decimal(0)))*q
        effective_legacy=item.get('effective_legacy_unit_rub')
        delivered_q=Decimal(str(row.get('base_purchase_expensed',0)))/Decimal(str(row.get('supplier_price_fact') or row.get('base_price') or 1))
        effective_old=Decimal(str(row.get("custom_delivery_fee") or 0))*delivered_q if effective_legacy is None else Decimal(str(effective_legacy))*delivered_q
        fact=item.get('carrier_fact_amount_rub')
        own_fact=fact is not None
        estimated=planned
        if isinstance(snapshot,dict) and fact is None:
            insurance_rate=next((Decimal(str(c.get('rate') or 0)) for c in snapshot.get('components',[]) if c['code']=='carrier_insurance'),Decimal(0))
            if insurance_rate and pd.notna(row.get('sell_price')):
                estimated=comps.get('carrier_delivery',Decimal(0))*q+Decimal(str(row['sell_price']))*insurance_rate/100
        own=Decimal(str(fact)) if own_fact else estimated
        if item.get('carrier_known_amount_rub') is not None:
            uncovered=max(Decimal(0),q-Decimal(str(item.get('carrier_known_quantity') or 0)))
            own=Decimal(str(item['carrier_known_amount_rub']))+estimated*uncovered/q
        # Legacy cost was already expensed by calc_economics on delivered units.
        old_expensed=Decimal(str(row.get('custom_delivery_fee') or 0))*delivered_q
        adjustment=old_expensed-effective_old-own
        if row.get('is_cancelled_before',False) and not own_fact:
            own=Decimal(0)
            adjustment=old_expensed-effective_old
        out.at[index,'planned_custom_delivery_fee_total']=float(old_plan)
        out.at[index,'effective_custom_delivery_fee_total']=float(effective_old)
        out.at[index,'carrier_delivery_plan_total']=float(planned)
        out.at[index,'carrier_delivery_fact_total']=float(fact) if own_fact else None
        out.at[index,'carrier_delivery_effective_total']=float(own)
        out.at[index,'carrier_expense_correction_reason']=item.get('correction_reason')
        out.at[index,'carrier_allocation_estimated']=bool(item.get('allocation_estimated',False))
        out.at[index,'carrier_expenses_estimated']=bool(metadata.get('incomplete') or (own!=0 and ((fact is None) or item.get('allocation_estimated') or item.get('carrier_has_unpaid_parcel') or (item.get('carrier_fact_quantity') is not None and Decimal(str(item['carrier_fact_quantity']))<q))))
        for key in ['profit','profit_no_promo','margin_fact_rub']:
            if key in out and pd.notna(row.get(key)):
                out.at[index,key]=float(Decimal(str(row[key]))+adjustment)
        # Не превращать отсутствующую выплату (actual_profit=0) в полученную прибыль.
        paid=row.get('payment_status')=='Переведён'
        if paid and pd.notna(row.get('actual_profit')):
            out.at[index,'actual_profit']=float(Decimal(str(row['actual_profit']))+adjustment)
        out.at[index,'our_costs']=float(Decimal(str(row['our_costs']))-adjustment)
        profit=Decimal(str(out.at[index,'profit']))
        for field,denominator in [('margin_fact_pct',row.get('sell_price')),('margin_fact_on_cost_pct',row.get('effective_purchase_total'))]:
            if denominator and pd.notna(denominator):out.at[index,field]=float(profit/Decimal(str(denominator))*100)
        out.at[index,'profit_vs_expected']=float(profit-Decimal(str(row.get('expected_profit') or 0)))
        out.at[index,'is_loss']=profit<0
        details=row.get('report_service_details')
        cross=Decimal(str((details or {}).get('cross_border_delivery') or 0)) if isinstance(details,dict) else 0
        out.at[index,'carrier_reconciliation_required']=bool(own_fact and cross>0 and not item.get("reconciliation_resolved"))
        if out.at[index,'carrier_expenses_estimated'] or out.at[index,'carrier_reconciliation_required']:
            out.at[index,'economics_is_estimated']=True
    return out


def apply_mm_carrier_expenses(frame,evidence):
    out=frame.copy()
    lookup={int(r['item_id']):r for r in evidence}
    for index,row in out.iterrows():
        ev=lookup.get(int(row['item_id']),{})
        snap=row.get('pricing_snapshot')
        comps={c['code']:Decimal(str(c['amount'])) for c in snap.get('components',[])} if isinstance(snap,dict) else {}
        planned=(comps.get('carrier_delivery',Decimal(0))+comps.get('carrier_insurance',Decimal(0)))*Decimal(str(row['quantity']))
        fact=ev.get('carrier_fact_amount_rub')
        estimated=planned
        if isinstance(snap,dict) and fact is None:
            rate=next((Decimal(str(c.get('rate') or 0)) for c in snap.get('components',[]) if c['code']=='carrier_insurance'),Decimal(0))
            if rate and pd.notna(row.get('sell_price')):
                estimated=comps.get('carrier_delivery',Decimal(0))*Decimal(str(row['quantity']))+Decimal(str(row['sell_price']))*rate/100
        own=Decimal(str(fact)) if fact is not None else estimated
        if ev.get('carrier_known_amount_rub') is not None:
            q=Decimal(str(row['quantity']))
            uncovered=max(Decimal(0),q-Decimal(str(ev.get('carrier_known_quantity') or 0)))
            own=Decimal(str(ev['carrier_known_amount_rub']))+estimated*uncovered/q
        if row.get('is_cancelled_before',False) and fact is None:
            own=Decimal(0)
        if isinstance(snap,dict) and snap.get('prices') and snap.get('source'):
            unit=Decimal(str(snap['prices']['target_price']))-Decimal(str(snap['source']['purchase_price_rub']))-sum(v for k,v in comps.items() if k!='margin')
            out.at[index,'expected_profit']=float(unit*Decimal(str(row['quantity'])))
        out.at[index,'carrier_delivery_plan_total']=float(planned)
        out.at[index,'carrier_delivery_fact_total']=float(fact) if fact is not None else None
        out.at[index,'carrier_delivery_effective_total']=float(own)
        out.at[index,'carrier_expenses_estimated']=bool(own!=0 and (fact is None or ev.get('allocation_estimated') or ev.get('carrier_has_unpaid_parcel') or (ev.get('carrier_fact_quantity') is not None and Decimal(str(ev['carrier_fact_quantity']))<Decimal(str(row['quantity'])))))
        out.at[index,'our_costs']=float(Decimal(str(row['our_costs']))+own)
        for key in ['profit','profit_no_promo','margin_fact_rub']:
            if key in out:out.at[index,key]=float(Decimal(str(row[key]))-own)
        if row.get('payment_status')=='Переведён':
            out.at[index,'actual_profit']=float(Decimal(str(row['actual_profit']))-own)
        for key,base in [('margin_pct','sell_price'),('margin_fact_pct','sell_price'),('margin_fact_on_cost_pct','effective_purchase_total')]:
            if row.get(base):out.at[index,key]=out.at[index,'profit']/row[base]*100
        out.at[index,'carrier_reconciliation_required']=bool(fact is not None and row.get('cdek_delivery_cost',0)>0 and not ev.get('reconciliation_resolved'))
        out.at[index,'economics_is_estimated']=bool(row.get('economics_is_estimated',False) or ((snap.get('decision') or {}).get('metadata',{}).get('carrier_delivery',{}).get('incomplete',False) if isinstance(snap,dict) else False) or out.at[index,'carrier_expenses_estimated'] or out.at[index,'carrier_reconciliation_required'] or not row.get('uses_fact_purchase_price',False))
    return out
