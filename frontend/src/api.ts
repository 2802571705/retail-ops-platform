export interface User { id: number; email: string; display_name: string; role: string }
export interface Session { access_token: string; token_type: string; user: User }
export interface Store { id: number; name: string; city: string; address: string }
export interface Product { product_id: number; sku: string; name: string; category: string; unit: string; price_cents: number; price_version: number; available_qty: number; available: boolean }
export interface Bundle { bundle_id: number; name: string; price_cents: number; price_version: number; available_qty: number; available: boolean; components: { product_id: number; name: string; quantity: number }[] }
export interface Coupon { user_coupon_id: number; name: string; status: string; scope: string; store_id: number | null; min_spend_cents: number; discount_cents: number; starts_at: string; ends_at: string }
export interface OrderSummary { id: number; store_id: number; order_source: string; status: string; payable_cents: number; created_at: string }
export interface Order extends OrderSummary { user_id: number; employee_id: number | null; gross_cents: number; coupon_discount_cents: number; points_used: number; points_discount_cents: number; user_coupon_id: number | null; paid_at: string | null; items: { id: number; item_type: 'PRODUCT' | 'BUNDLE'; product_id: number | null; bundle_id: number | null; item_name: string; price_version_snapshot: number; quantity: number; unit_price_cents: number; line_total_cents: number; components: { product_id: number; quantity: number }[] }[] }
export interface CreateOrder { store_id: number; items: { item_type: 'PRODUCT' | 'BUNDLE'; product_id?: number; bundle_id?: number; quantity: number; expected_price_version: number }[]; user_coupon_id: number | null; points_used: number }
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); this.name = 'ApiError'; }
}
export async function api<T>(path: string, token?: string, options: { method?: string; body?: unknown; key?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.key) headers['Idempotency-Key'] = options.key;
  const response = await fetch(`/api${path}`, { method: options.method ?? 'GET', headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && token) window.dispatchEvent(new CustomEvent('retailops:unauthorized', { detail: token }));
    const fields = Array.isArray(result?.error?.fields) ? result.error.fields.map((f: { field: string; message: string }) => `${f.field}: ${f.message}`).join('；') : '';
    throw new ApiError(response.status, result?.error?.code ?? `HTTP_${response.status}`, [result?.error?.message ?? `请求失败（${response.status}）`, fields].filter(Boolean).join('：'));
  }
  if (!result || !('data' in result)) throw new Error('服务器响应无法解析，请查询业务结果后重试。');
  return result.data as T;
}
export const money = (cents: number) => `¥${(cents / 100).toFixed(2)}`;
export const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
const labels: Record<string,string> = { PENDING_PAYMENT:'待支付',PAID:'已支付',COMPLETED:'已完成',CANCELLED:'已取消',AVAILABLE:'未核销',REDEEMED:'已核销',EXPIRED:'已过期' };
export const statusText = (status: string) => labels[status] ?? status;
export const message = (e: unknown) => e instanceof ApiError ? e.message : '连接失败或响应未确认，请确认后端运行后重试。';
