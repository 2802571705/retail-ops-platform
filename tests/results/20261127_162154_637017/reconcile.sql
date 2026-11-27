-- 连接数据库 retailops_accept_20261127_162154_637017（不是日常经营库）

-- C01
SELECT o.id,o.status,o.payable_cents,o.points_used,o.user_coupon_id,
  (SELECT count(*) FROM payments p WHERE p.order_id=o.id) AS payments,
  (SELECT coalesce(sum(amount_cents),0) FROM payments p WHERE p.order_id=o.id) AS payment_cents,
  (SELECT count(*) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_rows,
  (SELECT coalesce(sum(delta_qty),0) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_delta,
  (SELECT count(*) FROM points_ledger l WHERE l.order_id=o.id) AS point_rows,
  (SELECT coalesce(sum(delta_points),0) FROM points_ledger l WHERE l.order_id=o.id) AS point_delta,
  (SELECT count(*) FROM user_coupons c WHERE c.redeemed_order_id=o.id) AS redeemed_coupons
  FROM orders o WHERE o.id=ANY(ARRAY[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100]::bigint[]) ORDER BY o.id;

-- C02
SELECT o.id,o.status,o.payable_cents,o.points_used,o.user_coupon_id,
  (SELECT count(*) FROM payments p WHERE p.order_id=o.id) AS payments,
  (SELECT coalesce(sum(amount_cents),0) FROM payments p WHERE p.order_id=o.id) AS payment_cents,
  (SELECT count(*) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_rows,
  (SELECT coalesce(sum(delta_qty),0) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_delta,
  (SELECT count(*) FROM points_ledger l WHERE l.order_id=o.id) AS point_rows,
  (SELECT coalesce(sum(delta_points),0) FROM points_ledger l WHERE l.order_id=o.id) AS point_delta,
  (SELECT count(*) FROM user_coupons c WHERE c.redeemed_order_id=o.id) AS redeemed_coupons
  FROM orders o WHERE o.id=ANY(ARRAY[101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200]::bigint[]) ORDER BY o.id;

-- C03
SELECT o.id,o.status,o.payable_cents,o.points_used,o.user_coupon_id,
  (SELECT count(*) FROM payments p WHERE p.order_id=o.id) AS payments,
  (SELECT coalesce(sum(amount_cents),0) FROM payments p WHERE p.order_id=o.id) AS payment_cents,
  (SELECT count(*) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_rows,
  (SELECT coalesce(sum(delta_qty),0) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_delta,
  (SELECT count(*) FROM points_ledger l WHERE l.order_id=o.id) AS point_rows,
  (SELECT coalesce(sum(delta_points),0) FROM points_ledger l WHERE l.order_id=o.id) AS point_delta,
  (SELECT count(*) FROM user_coupons c WHERE c.redeemed_order_id=o.id) AS redeemed_coupons
  FROM orders o WHERE o.id=ANY(ARRAY[201]::bigint[]) ORDER BY o.id;

-- C04
SELECT o.id,o.status,o.payable_cents,o.points_used,o.user_coupon_id,
  (SELECT count(*) FROM payments p WHERE p.order_id=o.id) AS payments,
  (SELECT coalesce(sum(amount_cents),0) FROM payments p WHERE p.order_id=o.id) AS payment_cents,
  (SELECT count(*) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_rows,
  (SELECT coalesce(sum(delta_qty),0) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_delta,
  (SELECT count(*) FROM points_ledger l WHERE l.order_id=o.id) AS point_rows,
  (SELECT coalesce(sum(delta_points),0) FROM points_ledger l WHERE l.order_id=o.id) AS point_delta,
  (SELECT count(*) FROM user_coupons c WHERE c.redeemed_order_id=o.id) AS redeemed_coupons
  FROM orders o WHERE o.id=ANY(ARRAY[202]::bigint[]) ORDER BY o.id;

-- C05
SELECT o.id,o.status,o.payable_cents,o.points_used,o.user_coupon_id,
  (SELECT count(*) FROM payments p WHERE p.order_id=o.id) AS payments,
  (SELECT coalesce(sum(amount_cents),0) FROM payments p WHERE p.order_id=o.id) AS payment_cents,
  (SELECT count(*) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_rows,
  (SELECT coalesce(sum(delta_qty),0) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_delta,
  (SELECT count(*) FROM points_ledger l WHERE l.order_id=o.id) AS point_rows,
  (SELECT coalesce(sum(delta_points),0) FROM points_ledger l WHERE l.order_id=o.id) AS point_delta,
  (SELECT count(*) FROM user_coupons c WHERE c.redeemed_order_id=o.id) AS redeemed_coupons
  FROM orders o WHERE o.id=ANY(ARRAY[203]::bigint[]) ORDER BY o.id;