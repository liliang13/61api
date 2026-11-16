/**
 * 网关对外地址。
 * - 私有化部署默认同源,由反向代理把 /v1 转到本机网关;
 * - 公开运营构建时用 VITE_API_ORIGIN 指定独立 API 域名(如 https://api.61api.cn);
 * - 本地开发走 Vite 代理同源。
 */
const configured = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/+$/, '')
export const API_ORIGIN = configured || location.origin
export const API_BASE_URL = API_ORIGIN + '/v1'
