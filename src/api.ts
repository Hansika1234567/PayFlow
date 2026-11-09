/**
 * PayFlow API Client
 * Centralized fetch wrapper handling JWT authentication,
 * API error parsing, and typed request/response contracts.
 */

const API_BASE = '/api/v1';

export interface WalletData {
  id: number;
  user_id: number;
  balance_cents: number;
  balance_dollars: number;
  currency: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface UserData {
  id: number;
  email: string;
  username: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  wallet?: WalletData;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  user: UserData;
}

export interface TransferReceipt {
  transaction_id: string;
  idempotency_key: string;
  sender_username: string;
  receiver_username: string;
  amount_cents: number;
  amount_dollars: number;
  currency: string;
  status: string;
  description?: string;
  created_at: string;
  sender_balance_after_dollars?: number;
}

export interface LedgerItem {
  id: number;
  transaction_id: string;
  entry_type: 'DEBIT' | 'CREDIT';
  amount_cents: number;
  amount_dollars: number;
  balance_after_dollars: number;
  description?: string;
  counterparty_username?: string;
  created_at: string;
}

export interface PaginatedLedger {
  items: LedgerItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface TransactionHistoryItem {
  id: string;
  type: 'SENT' | 'RECEIVED';
  counterparty_username: string;
  counterparty_full_name: string;
  amount_cents: number;
  amount_dollars: number;
  currency: string;
  status: string;
  description?: string;
  created_at: string;
}

export interface PaginatedTransactions {
  items: TransactionHistoryItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export function getStoredToken(): string | null {
  return localStorage.getItem('payflow_token');
}

export function setStoredToken(token: string) {
  localStorage.setItem('payflow_token', token);
}

export function removeStoredToken() {
  localStorage.removeItem('payflow_token');
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (response.status === 401) {
      removeStoredToken();
    }
    const errorMsg = data.detail || data.message || `Request failed with status ${response.status}`;
    throw new Error(errorMsg);
  }

  return data as T;
}

export const api = {
  // Auth
  register: (payload: { email: string; username: string; password: string; full_name: string }) =>
    request<AuthResponse>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),

  login: (payload: { email_or_username: string; password: string }) =>
    request<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),

  getMe: () => request<UserData>('/auth/me'),

  // Wallets
  getMyWallet: () => request<WalletData>('/wallets/me'),

  deposit: (payload: { amount: number; description?: string; idempotency_key?: string }) =>
    request<WalletData>('/wallets/deposit', { method: 'POST', body: JSON.stringify(payload) }),

  // Transfers
  transfer: (payload: { receiver_username: string; amount: number; idempotency_key: string; description?: string }) =>
    request<TransferReceipt>('/transfers', { method: 'POST', body: JSON.stringify(payload) }),

  getTransfer: (txId: string) => request<TransferReceipt>(`/transfers/${txId}`),

  // Ledger & History
  getLedger: (params: { entry_type?: string; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.entry_type) query.append('entry_type', params.entry_type);
    if (params.limit !== undefined) query.append('limit', String(params.limit));
    if (params.offset !== undefined) query.append('offset', String(params.offset));
    return request<PaginatedLedger>(`/ledger?${query.toString()}`);
  },

  getTransactions: (params: { filter_type?: string; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.filter_type) query.append('filter_type', params.filter_type);
    if (params.limit !== undefined) query.append('limit', String(params.limit));
    if (params.offset !== undefined) query.append('offset', String(params.offset));
    return request<PaginatedTransactions>(`/transactions?${query.toString()}`);
  },
};
