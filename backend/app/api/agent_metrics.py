"""确定性只读经营工具，不执行模型生成的 SQL。"""
from datetime import date, datetime, time, timedelta
from sqlalchemy import text
from app.api.hq_common import CHINA_TZ, check_store_filter
from app.api.orders import fail

RULES = {"price_step_percent": 5, "max_change_percent": 10,
         "minimum_margin_percent": 20, "cooldown_hours": 24,
         "minimum_sales_units": 5, "growth_percent": 20,
         "tight_cover_days": 3, "high_cover_days": 14, "target_cover_days": 7}


def scope(db, date_from, date_to, store_id):
    today = datetime.now(CHINA_TZ).date()
    days = (date_to - date_from).days + 1
    if not 1 <= days <= 30 or date_to >= today:
        fail("INVALID_DATE_RANGE", "请选择截至昨天的1至30个完整北京时间业务日", 422)
    check_store_filter(db, store_id)
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "store_id": store_id, "days": days, "timezone": "Asia/Shanghai"}


def params(s):
    start = date.fromisoformat(s['date_from']); end = date.fromisoformat(s['date_to']) + timedelta(days=1)
    return {"start": datetime.combine(start, time.min, CHINA_TZ),
            "end": datetime.combine(end, time.min, CHINA_TZ),
            "prev": datetime.combine(start - timedelta(days=s['days']), time.min, CHINA_TZ),
            "store": s['store_id']}


METRICS_SQL = """
WITH paid AS (
 SELECT id, store_id, paid_at FROM orders
 WHERE status IN ('PAID','COMPLETED') AND paid_at >= :prev AND paid_at < :end
 AND (CAST(:store AS bigint) IS NULL OR store_id = :store)
), units AS (
 SELECT o.store_id, i.product_id,
 COALESCE(SUM(i.quantity) FILTER (WHERE o.paid_at >= :start),0) AS sold_qty,
 COALESCE(SUM(i.quantity) FILTER (WHERE o.paid_at < :start),0) AS previous_qty,
 COALESCE(SUM(i.line_total_cents) FILTER (WHERE o.paid_at >= :start),0) AS gross_cents
 FROM paid o JOIN order_items i ON i.order_id=o.id AND i.item_type='PRODUCT'
 GROUP BY o.store_id,i.product_id
), consumption AS (
 SELECT o.store_id,c.product_id,SUM(c.quantity) AS consumed_qty
 FROM paid o JOIN order_items i ON i.order_id=o.id
 JOIN order_item_components c ON c.order_item_id=i.id
 WHERE o.paid_at >= :start GROUP BY o.store_id,c.product_id
)
SELECT sp.store_id,s.name AS store_name,sp.product_id,p.name AS product_name,p.sku,
 sp.price_cents,sp.price_version,sp.estimated_cost_cents,sp.min_price_cents,sp.max_price_cents,
 sp.last_price_changed_at, now() AS observed_at, inv.available_qty,
 COALESCE(u.sold_qty,0) AS sold_qty,COALESCE(u.previous_qty,0) AS previous_qty,
 COALESCE(u.gross_cents,0) AS gross_cents,COALESCE(c.consumed_qty,0) AS consumed_qty
 FROM store_products sp JOIN stores s ON s.id=sp.store_id
 JOIN products p ON p.id=sp.product_id
 JOIN inventory inv ON inv.store_id=sp.store_id AND inv.product_id=sp.product_id
 LEFT JOIN units u ON u.store_id=sp.store_id AND u.product_id=sp.product_id
 LEFT JOIN consumption c ON c.store_id=sp.store_id AND c.product_id=sp.product_id
 WHERE s.status='OPEN' AND p.status='ACTIVE' AND sp.is_active
 AND (CAST(:store AS bigint) IS NULL OR sp.store_id=:store)
 AND (CAST(:product AS bigint) IS NULL OR sp.product_id=:product)
 ORDER BY sp.store_id,sp.product_id
"""


def price_allowed(r, new):
    old, cost = r['price_cents'], r['estimated_cost_cents']
    return (old > 0 and new > 0 and new != old and cost is not None
            and abs(new-old)*100 <= old*RULES["max_change_percent"] and (new-cost)*100 >= new*RULES["minimum_margin_percent"]
            and r['min_price_cents'] <= new <= r['max_price_cents']
            and (r['last_price_changed_at'] is None or
                 r['observed_at']-r['last_price_changed_at'] >= timedelta(hours=RULES["cooldown_hours"])))


def metrics(db, s, product_id=None):
    result = []
    for row in db.execute(text(METRICS_SQL), {**params(s), 'product': product_id}).mappings():
        r = dict(row)
        # PostgreSQL 的 SUM(bigint) 返回 Decimal，统一保留整数分及整数件。
        for k in ('sold_qty','previous_qty','gross_cents','consumed_qty'):
            r[k] = int(r[k])
        q, prev, used, stock, days = (r['sold_qty'],r['previous_qty'],r['consumed_qty'],r['available_qty'],s['days'])
        cover = stock*days/used if used else None
        r['cover_days'] = round(cover,2) if cover is not None else None
        r['growth_percent'] = round((q-prev)*100/prev,2) if prev else None
        r['replenish_qty'] = max(0, (used*RULES["target_cover_days"]+days-1)//days-stock)
        r['direction'] = None; r['suggested_price_cents'] = None; r['reason'] = ''
        old = r['price_cents']; new = old
        if q >= RULES["minimum_sales_units"] and prev > 0 and q*100 >= prev*(100+RULES["growth_percent"]) and used > 0 and stock*days <= RULES["tight_cover_days"]*used:
            new = (old*(100+RULES["price_step_percent"])+50)//100
            direction, reason = 'PRICE_INCREASE',f'单品销量较上期增长至少{RULES["growth_percent"]}%，当前库存覆盖不超过{RULES["tight_cover_days"]}天'
        elif prev >= RULES["minimum_sales_units"] and q*100 <= prev*(100-RULES["growth_percent"]) and stock > 0 and (used == 0 or stock*days >= RULES["high_cover_days"]*used):
            new = (old*(100-RULES["price_step_percent"])+50)//100
            direction, reason = 'DISCOUNT_PRICE',f'单品销量较上期下降至少{RULES["growth_percent"]}%，库存覆盖至少{RULES["high_cover_days"]}天或期间无消耗'
        else:
            direction, reason = None, '未达到销量与库存联合筛选条件'
        if direction and s['date_to'] != (datetime.now(CHINA_TZ).date()-timedelta(days=1)).isoformat():
            direction, reason = None, '调价分析须截至昨天，以免使用过期经营窗口'
        if direction and price_allowed(r,new):
            r['direction'],r['suggested_price_cents'],r['reason'] = direction,new,reason
        else:
            r['reason'] = reason if not direction else ('建议价按分取整后与原价相同' if new == old else f'符合经营筛选，但成本、价格边界、毛利或{RULES["cooldown_hours"]}小时冷却条件不满足')
        for k in ('last_price_changed_at','observed_at'):
            r[k] = r[k].isoformat() if r[k] is not None else None
        result.append(r)
    return result


def tool_result(db, s, name):
    rows = metrics(db,s)
    if name == 'replenishment':
        rows = sorted((r for r in rows if r['replenish_qty']>0),key=lambda r:-r['replenish_qty'])
    elif name == 'price_candidates':
        # 优先展示有较多近期销量依据的候选；同销量按门店与 SKU 稳定排序。
        rows = sorted((r for r in rows if r['direction']), key=lambda r: (-max(r['sold_qty'],r['previous_qty']),r['store_id'],r['product_id']))
    elif name == 'sku_sales':
        rows = sorted(rows,key=lambda r:-r['sold_qty'])
    else:
        raise ValueError('unknown tool')
    # 模型只接收经营汇总，不传输消费者明细或原始成本。
    keys = ['store_id','store_name','product_id','product_name','sku','sold_qty','previous_qty',
            'gross_cents','consumed_qty','available_qty','cover_days','growth_percent']
    if name == 'replenishment': keys += ['replenish_qty']
    if name == 'price_candidates': keys += ['price_cents','price_version','suggested_price_cents','direction','reason']
    return {'scope':s,'total':len(rows),'items':[{k:r[k] for k in keys} for r in rows[:50]],
            'truncated':len(rows)>50,'rules':RULES,
            'metric_notes':'单品销量及优惠前金额不含套餐；库存消耗包含套餐组成快照；库存为当前快照；无消耗时覆盖天数不可计算；上期销量为零时增长率不可计算（null 不是零）；调价候选按相邻两期较高销量降序；不推断价格因果效应。'}
