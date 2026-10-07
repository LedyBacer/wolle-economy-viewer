"""Независимая сверка доставленных заказов; производственная БД только READ ONLY."""
import argparse
import json,pathlib
import pandas as pd
from sqlalchemy import text
from wolle_economy.db.engine import get_engine
from wolle_economy.db.queries import build_order_items_query,build_payment_aggregates_query,build_supplier_price_fact_query
from wolle_economy.domain.economics import calc_economics,merge_with_payments,aggregate_yandex_orders
ids=[61616926403,60262088066,60753056642,60653273408,61393666626,61725442371,62028170690,62137243906]
ids += [62527350787,62358261187,62061729729,62003818947,61985005186]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--orders',nargs='+',type=int,default=ids)
parser.add_argument('--output',type=pathlib.Path)
args=parser.parse_args()
ids=args.orders
results=[]
with get_engine().connect() as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 for oid in ids:
  oq,op=build_order_items_query(order_id=str(oid));pq,pp=build_payment_aggregates_query(order_id=str(oid));sq,sp=build_supplier_price_fact_query(order_id=str(oid))
  orders=pd.read_sql_query(oq,c,params=op);payments=pd.read_sql_query(pq,c,params=pp);supplier=pd.read_sql_query(sq,c,params=sp)
  if orders.empty:raise ValueError(f"Нет заказа {oid}")
  source=merge_with_payments(orders.merge(supplier,on='item_id',how='left'),payments)
  result=calc_economics(source);order=aggregate_yandex_orders(result).iloc[0]
  gross=float(orders.sell_price.iloc[0]) if pd.notna(orders.sell_price.iloc[0]) else float(((orders.buyer_price+orders.subsidy)*orders.quantity).sum())
  services=float(orders.market_services.iloc[0] or 0)
  returns=float(orders.returned_sell_price.fillna(0).sum())
  promo=float(source.wallet_promo_discounts.fillna(0).sum()) if source.wallet_promo_available.any() else float(source.promo_discounts.fillna(0).iloc[0])
  boost=float(source.boost_wallet_spend.fillna(0).iloc[0])
  costs=0
  for _,r in source.iterrows():
   q=float(r.tr_delivered_quantity) if pd.notna(r.tr_delivered_quantity) else float(r.quantity)
   purchase=float(r.supplier_price_fact) if pd.notna(r.supplier_price_fact) and r.supplier_price_fact>0 else float(r.base_price)
   snapshot = r.get('pricing_snapshot')
   own = float(r.ff_fee or 0)+float(r.socket_adapter_fee or 0)+float(r.custom_delivery_fee or 0)
   if isinstance(snapshot,dict) and snapshot.get('calculation_version') == 'yandex-v2-full-fees' and snapshot.get('snapshot_source') != 'order_recalculation':
    if not (pd.notna(r.supplier_price_fact) and r.supplier_price_fact>0):
     purchase=float(snapshot['source']['purchase_price_rub'])
    own=sum(float(component['amount']) for component in snapshot['components'] if component['code'] in ('ff','socket_adapter','custom_delivery'))
   costs+=(purchase+own)*q
  expected=gross-returns-services+promo+boost-costs
  assert abs(order.profit-expected)<.0001,(oid,order.profit,expected)
  assert abs(result.sell_price.sum()-(gross-returns))<.0001
  results.append(dict(order_id=oid,items=len(result),sale=gross-returns,cash_services=services,promo=promo,boost_wallet=boost,costs=costs,profit=round(order.profit,5),independent_profit=round(expected,5)))
 c.rollback()
if args.output:
 args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
