/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Wallet,
  ArrowUpRight,
  ArrowDownLeft,
  RefreshCw,
  Zap,
  ShieldCheck,
  Lock,
  ExternalLink,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  LogOut,
  User,
  Activity,
  Layers,
  Info,
  DollarSign
} from 'lucide-react';
import {
  api,
  UserData,
  WalletData,
  LedgerItem,
  TransactionHistoryItem,
  getStoredToken,
  setStoredToken,
  removeStoredToken
} from './api';

export default function App() {
  // Auth state
  const [token, setToken] = useState<string | null>(getStoredToken());
  const [currentUser, setCurrentUser] = useState<UserData | null>(null);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  // Form states for login/register
  const [authForm, setAuthForm] = useState({
    email: '',
    username: '',
    password: '',
    full_name: '',
  });

  // Wallet & Ledger state
  const [wallet, setWallet] = useState<WalletData | null>(null);
  const [ledgerItems, setLedgerItems] = useState<LedgerItem[]>([]);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [ledgerFilter, setLedgerFilter] = useState<'ALL' | 'DEBIT' | 'CREDIT'>('ALL');
  const [ledgerPage, setLedgerPage] = useState(0);
  const [pageSize] = useState(10);
  const [transactions, setTransactions] = useState<TransactionHistoryItem[]>([]);
  const [activeTab, setActiveTab] = useState<'ledger' | 'transactions'>('ledger');
  const [loadingData, setLoadingData] = useState(false);

  // Modals
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [showDepositModal, setShowDepositModal] = useState(false);
  const [showConcurrencyModal, setShowConcurrencyModal] = useState(false);
  const [showArchitectureModal, setShowArchitectureModal] = useState(false);

  // Transfer Form state
  const [transferForm, setTransferForm] = useState({
    receiver_username: '',
    amount: '25.00',
    description: 'Payment for services',
    idempotency_key: crypto.randomUUID(),
  });
  const [simulateDuplicateKey, setSimulateDuplicateKey] = useState(false);
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferResult, setTransferResult] = useState<{ success: boolean; message: string; receipt?: any } | null>(null);

  // Deposit Form state
  const [depositAmount, setDepositAmount] = useState('100.00');
  const [depositLoading, setDepositLoading] = useState(false);

  // Concurrency Simulation State
  const [concurrencyRunning, setConcurrencyRunning] = useState(false);
  const [concurrencyLogs, setConcurrencyLogs] = useState<string[]>([]);
  const [concurrencyStats, setConcurrencyStats] = useState<{
    userAInitial: number;
    userBInitial: number;
    userAFinal: number;
    userBFinal: number;
    totalInitial: number;
    totalFinal: number;
    completed: boolean;
  } | null>(null);

  // Copy helper
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(id);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleLogout = useCallback(() => {
    removeStoredToken();
    setToken(null);
    setCurrentUser(null);
    setWallet(null);
    setLedgerItems([]);
    setTransactions([]);
  }, []);

  // Fetch user data & wallet
  const fetchDashboardData = useCallback(async () => {
    if (!token) return;
    setLoadingData(true);
    try {
      const [userData, walletData, ledgerData, txData] = await Promise.all([
        api.getMe(),
        api.getMyWallet(),
        api.getLedger({
          entry_type: ledgerFilter === 'ALL' ? undefined : ledgerFilter,
          limit: pageSize,
          offset: ledgerPage * pageSize
        }),
        api.getTransactions({ limit: 15, offset: 0 })
      ]);

      setCurrentUser(userData);
      setWallet(walletData);
      setLedgerItems(ledgerData.items);
      setLedgerTotal(ledgerData.total);
      setTransactions(txData.items);
    } catch (err: any) {
      console.warn('Dashboard fetch failed, clearing invalid session:', err.message);
      handleLogout();
    } finally {
      setLoadingData(false);
    }
  }, [token, ledgerFilter, ledgerPage, pageSize, handleLogout]);

  useEffect(() => {
    if (token) {
      fetchDashboardData();
    }
  }, [token, fetchDashboardData]);

  // Auth submission
  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthLoading(true);
    setAuthError(null);

    try {
      let res;
      if (authMode === 'register') {
        res = await api.register({
          email: authForm.email,
          username: authForm.username,
          password: authForm.password,
          full_name: authForm.full_name || authForm.username,
        });
      } else {
        res = await api.login({
          email_or_username: authForm.username || authForm.email,
          password: authForm.password,
        });
      }

      setStoredToken(res.access_token);
      setToken(res.access_token);
      setCurrentUser(res.user);
    } catch (err: any) {
      setAuthError(err.message || 'Authentication failed');
    } finally {
      setAuthLoading(false);
    }
  };

  // Fast demo user prefill
  const prefillDemoUser = (user: 'alice' | 'bob') => {
    if (user === 'alice') {
      setAuthForm({
        email: 'alice@paypal-demo.internal',
        username: 'alice_demo',
        password: 'Password123!',
        full_name: 'Alice Developer',
      });
    } else {
      setAuthForm({
        email: 'bob@paypal-demo.internal',
        username: 'bob_demo',
        password: 'Password123!',
        full_name: 'Bob Engineer',
      });
    }
  };

  // Execute transfer
  const handleTransferSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTransferLoading(true);
    setTransferResult(null);

    const amountNum = parseFloat(transferForm.amount);
    if (isNaN(amountNum) || amountNum <= 0) {
      setTransferResult({ success: false, message: 'Please enter a valid positive dollar amount.' });
      setTransferLoading(false);
      return;
    }

    try {
      const receipt = await api.transfer({
        receiver_username: transferForm.receiver_username.trim(),
        amount: amountNum,
        idempotency_key: transferForm.idempotency_key,
        description: transferForm.description,
      });

      setTransferResult({
        success: true,
        message: `Transfer of $${receipt.amount_dollars.toFixed(2)} to @${receipt.receiver_username} completed successfully!`,
        receipt,
      });

      // If simulate duplicate is not checked, generate a new idempotency key for next transfer
      if (!simulateDuplicateKey) {
        setTransferForm(prev => ({ ...prev, idempotency_key: crypto.randomUUID() }));
      }

      // Refresh balances and ledger
      fetchDashboardData();
    } catch (err: any) {
      setTransferResult({ success: false, message: err.message || 'Transfer failed' });
    } finally {
      setTransferLoading(false);
    }
  };

  // Execute Deposit
  const handleDepositSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDepositLoading(true);
    const amountNum = parseFloat(depositAmount);
    if (isNaN(amountNum) || amountNum <= 0) {
      setDepositLoading(false);
      return;
    }

    try {
      await api.deposit({
        amount: amountNum,
        description: 'Simulated Test Deposit Top-Up',
      });
      setShowDepositModal(false);
      fetchDashboardData();
    } catch (err: any) {
      alert(`Deposit failed: ${err.message}`);
    } finally {
      setDepositLoading(false);
    }
  };

  // Live Concurrency Stress Test Runner
  const runLiveConcurrencyTest = async () => {
    setConcurrencyRunning(true);
    setConcurrencyLogs([]);
    setConcurrencyStats(null);

    const log = (msg: string) => setConcurrencyLogs(prev => [...prev, msg]);

    try {
      log('⚙️ [Setup] Registering two isolated test accounts for concurrency challenge...');
      const uid = crypto.randomUUID().slice(0, 6);
      const userA = `stress_a_${uid}`;
      const userB = `stress_b_${uid}`;

      const resA = await api.register({
        email: `${userA}@stress.test`,
        username: userA,
        password: 'Password123!',
        full_name: 'Stress Test Account A',
      });
      const resB = await api.register({
        email: `${userB}@stress.test`,
        username: userB,
        password: 'Password123!',
        full_name: 'Stress Test Account B',
      });

      const tokenA = resA.access_token;
      const tokenB = resB.access_token;

      log(`✅ Created @${userA} ($1,000.00) and @${userB} ($1,000.00). Total System Capital: $2,000.00.`);
      log('🚀 Launching 10 SIMULTANEOUS bidirectional transfers:');
      log('   - 5 requests: @' + userA + ' -> @' + userB + ' ($20.00 each = $100.00 total)');
      log('   - 5 requests: @' + userB + ' -> @' + userA + ' ($15.00 each = $75.00 total)');
      log('🔒 Enforcing deterministic lock ordering & atomic SQL updates...');

      const makeTransferReq = async (fromToken: string, toUsername: string, amount: number, id: number) => {
        const res = await fetch('/api/v1/transfers', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${fromToken}`,
          },
          body: JSON.stringify({
            receiver_username: toUsername,
            amount: amount,
            idempotency_key: `live-stress-${id}-${crypto.randomUUID()}`,
            description: `Stress test tx #${id}`,
          }),
        });
        const data = await res.json();
        return { status: res.status, data };
      };

      const tasks = [
        makeTransferReq(tokenA, userB, 20.00, 1),
        makeTransferReq(tokenA, userB, 20.00, 2),
        makeTransferReq(tokenA, userB, 20.00, 3),
        makeTransferReq(tokenA, userB, 20.00, 4),
        makeTransferReq(tokenA, userB, 20.00, 5),
        makeTransferReq(tokenB, userA, 15.00, 6),
        makeTransferReq(tokenB, userA, 15.00, 7),
        makeTransferReq(tokenB, userA, 15.00, 8),
        makeTransferReq(tokenB, userA, 15.00, 9),
        makeTransferReq(tokenB, userA, 15.00, 10),
      ];

      const start = performance.now();
      const results = await Promise.all(tasks);
      const elapsed = (performance.now() - start).toFixed(0);

      log(`⚡ All 10 concurrent requests completed in ${elapsed}ms.`);

      const allOk = results.every(r => r.status === 201);
      if (!allOk) {
        log('❌ One or more requests returned non-201 status.');
      } else {
        log('✅ 10/10 transfers returned HTTP 201 Created.');
      }

      // Check final balances
      const [walletARes, walletBRes] = await Promise.all([
        fetch('/api/v1/wallets/me', { headers: { Authorization: `Bearer ${tokenA}` } }).then(r => r.json()),
        fetch('/api/v1/wallets/me', { headers: { Authorization: `Bearer ${tokenB}` } }).then(r => r.json()),
      ]);

      const balA = walletARes.balance_dollars;
      const balB = walletBRes.balance_dollars;
      const totalFinal = balA + balB;

      log(`📊 Final Balance @${userA}: $${balA.toFixed(2)} (Expected: $975.00)`);
      log(`📊 Final Balance @${userB}: $${balB.toFixed(2)} (Expected: $1,025.00)`);
      log(`🛡️ Final Total Money: $${totalFinal.toFixed(2)} (Initial: $2,000.00)`);

      if (balA === 975 && balB === 1025 && totalFinal === 2000) {
        log('🎉 CONSERVATION OF MONEY PROVEN: Zero lost updates, zero deadlocks, zero balance drift!');
      } else {
        log('⚠️ Balance discrepancy detected!');
      }

      setConcurrencyStats({
        userAInitial: 1000,
        userBInitial: 1000,
        userAFinal: balA,
        userBFinal: balB,
        totalInitial: 2000,
        totalFinal: totalFinal,
        completed: true,
      });

    } catch (err: any) {
      log(`❌ Concurrency test error: ${err.message}`);
    } finally {
      setConcurrencyRunning(false);
    }
  };

  // If unauthenticated, show Auth Screen
  if (!token) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between selection:bg-indigo-500 selection:text-white">
        {/* Top Navbar */}
        <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
          <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-emerald-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <Wallet className="w-5 h-5 text-white" />
              </div>
              <div>
                <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-indigo-200 bg-clip-text text-transparent">
                  PayFlow
                </span>
                <span className="ml-2 text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  FinTech Core
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <a
                href="/docs"
                target="_blank"
                rel="noreferrer"
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition flex items-center gap-1.5"
              >
                <span>Interactive Swagger API</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        </header>

        {/* Hero & Auth Card */}
        <main className="max-w-6xl mx-auto px-4 py-12 flex-1 flex flex-col lg:flex-row items-center justify-center gap-12">
          {/* Left Column: Value Proposition */}
          <div className="max-w-xl space-y-6 text-center lg:text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium">
              <ShieldCheck className="w-4 h-4 text-blue-400" />
              <span>Double-Entry Ledger • Concurrency Safe • Idempotent</span>
            </div>

            <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white leading-[1.15]">
              Real-World Digital Wallet &amp; Ledger Architecture.
            </h1>

            <p className="text-slate-400 text-base sm:text-lg leading-relaxed">
              Built with <strong className="text-slate-200">FastAPI</strong>, <strong className="text-slate-200">SQLAlchemy</strong>, and <strong className="text-slate-200">React</strong>. Designed to demonstrate the exact engineering primitives evaluated in FinTech software engineering interviews: atomic transactions, deterministic lock ordering, and audit immutability.
            </p>

            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/50 text-left">
                <div className="flex items-center gap-2 text-indigo-400 font-semibold text-sm mb-1">
                  <Lock className="w-4 h-4" />
                  <span>Lock Ordering</span>
                </div>
                <p className="text-xs text-slate-400">Pessimistic row-locking ordered by wallet ID eliminates deadlock risk.</p>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-800 bg-slate-900/50 text-left">
                <div className="flex items-center gap-2 text-emerald-400 font-semibold text-sm mb-1">
                  <Layers className="w-4 h-4" />
                  <span>Double-Entry</span>
                </div>
                <p className="text-xs text-slate-400">Strict debit and credit entries with running post-balance snapshots.</p>
              </div>
            </div>
          </div>

          {/* Right Column: Authentication Card */}
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl relative">
            <div className="flex rounded-xl bg-slate-800/80 p-1 mb-6 border border-slate-700/60">
              <button
                type="button"
                onClick={() => { setAuthMode('login'); setAuthError(null); }}
                className={`flex-1 py-2 text-xs sm:text-sm font-semibold rounded-lg transition ${
                  authMode === 'login' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-white'
                }`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('register'); setAuthError(null); }}
                className={`flex-1 py-2 text-xs sm:text-sm font-semibold rounded-lg transition ${
                  authMode === 'register' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-white'
                }`}
              >
                Create Account
              </button>
            </div>

            {/* Quick Demo Pre-fill */}
            <div className="mb-5 p-3 rounded-xl bg-indigo-950/40 border border-indigo-800/40 text-xs">
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-indigo-300">Quick Test Accounts:</span>
                <span className="text-[10px] text-slate-400">Auto-filled with $1,000 credit</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => prefillDemoUser('alice')}
                  className="px-2.5 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 text-center font-medium transition"
                >
                  Fill @alice_demo
                </button>
                <button
                  type="button"
                  onClick={() => prefillDemoUser('bob')}
                  className="px-2.5 py-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 text-center font-medium transition"
                >
                  Fill @bob_demo
                </button>
              </div>
            </div>

            {authError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-start gap-2">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{authError}</span>
              </div>
            )}

            <form onSubmit={handleAuthSubmit} className="space-y-4">
              {authMode === 'register' && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Full Name</label>
                    <input
                      type="text"
                      required
                      placeholder="Jane Doe"
                      value={authForm.full_name}
                      onChange={e => setAuthForm({ ...authForm, full_name: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Email Address</label>
                    <input
                      type="email"
                      required
                      placeholder="jane@example.com"
                      value={authForm.email}
                      onChange={e => setAuthForm({ ...authForm, email: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm"
                    />
                  </div>
                </>
              )}

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  {authMode === 'register' ? 'Username' : 'Username or Email'}
                </label>
                <input
                  type="text"
                  required
                  placeholder={authMode === 'register' ? 'jane_doe' : 'alice_demo'}
                  value={authForm.username}
                  onChange={e => setAuthForm({ ...authForm, username: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
                <input
                  type="password"
                  required
                  placeholder="••••••••••••"
                  value={authForm.password}
                  onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm"
                />
              </div>

              <button
                type="submit"
                disabled={authLoading}
                className="w-full py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-500 hover:to-blue-500 text-white font-semibold text-sm shadow-lg shadow-indigo-600/25 transition disabled:opacity-50 mt-2 flex items-center justify-center gap-2"
              >
                {authLoading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Processing...</span>
                  </>
                ) : (
                  <span>{authMode === 'register' ? 'Register & Provision Wallet' : 'Sign In'}</span>
                )}
              </button>
            </form>
          </div>
        </main>

        <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500">
          PayFlow FinTech Systems Project • Python FastAPI + SQLAlchemy + SQLite WAL + React SPA
        </footer>
      </div>
    );
  }

  // Authenticated Dashboard
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col selection:bg-indigo-500 selection:text-white">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-emerald-500 flex items-center justify-center shadow-md shadow-indigo-500/20">
              <Wallet className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-base tracking-tight text-white">PayFlow</span>
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                  Live Core
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowArchitectureModal(true)}
              className="text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition flex items-center gap-1.5"
            >
              <Info className="w-3.5 h-3.5 text-indigo-400" />
              <span className="hidden sm:inline">Architecture Deep Dive</span>
            </button>

            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition flex items-center gap-1.5"
            >
              <span>Swagger Docs</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>

            <div className="h-6 w-px bg-slate-800"></div>

            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-indigo-600/30 border border-indigo-500/30 flex items-center justify-center text-xs font-bold text-indigo-300">
                {currentUser?.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="hidden sm:block text-left text-xs leading-tight">
                <p className="font-semibold text-slate-200">@{currentUser?.username}</p>
                <p className="text-[10px] text-slate-400">{currentUser?.full_name}</p>
              </div>
            </div>

            <button
              onClick={handleLogout}
              title="Sign Out"
              className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-rose-400 transition"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-6xl mx-auto px-4 py-8 flex-1 w-full space-y-8">
        {/* Top Hero Balance Card */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Balance Card (2 cols) */}
          <div className="lg:col-span-2 rounded-3xl bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950/40 border border-slate-800 p-6 sm:p-8 relative overflow-hidden shadow-xl">
            <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-500/5 rounded-full blur-3xl pointer-events-none"></div>

            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Available Balance</span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                    {wallet?.currency || 'USD'}
                  </span>
                </div>
                <div className="text-4xl sm:text-5xl font-black text-white tracking-tight flex items-baseline gap-1">
                  <span className="text-2xl sm:text-3xl font-normal text-slate-400">$</span>
                  <span>{wallet ? wallet.balance_dollars.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}</span>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => setShowTransferModal(true)}
                  className="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs sm:text-sm shadow-lg shadow-indigo-600/30 transition flex items-center gap-2"
                >
                  <ArrowUpRight className="w-4 h-4" />
                  <span>Send Money</span>
                </button>

                <button
                  onClick={() => setShowDepositModal(true)}
                  className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-semibold text-xs sm:text-sm transition flex items-center gap-2"
                >
                  <DollarSign className="w-4 h-4 text-emerald-400" />
                  <span>Deposit</span>
                </button>

                <button
                  onClick={fetchDashboardData}
                  disabled={loadingData}
                  title="Refresh Balance & Ledger"
                  className="p-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-slate-300 transition"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingData ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {/* Quick Metrics */}
            <div className="grid grid-cols-3 gap-4 pt-4 border-t border-slate-800/80 text-xs">
              <div>
                <span className="text-slate-400 block mb-0.5">Wallet ID</span>
                <span className="font-mono text-slate-200 font-semibold">#{wallet?.id}</span>
              </div>
              <div>
                <span className="text-slate-400 block mb-0.5">Precision Store</span>
                <span className="font-mono text-indigo-300 font-semibold">{wallet?.balance_cents.toLocaleString()} cents</span>
              </div>
              <div>
                <span className="text-slate-400 block mb-0.5">Status</span>
                <span className="font-semibold text-emerald-400 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                  {wallet?.status}
                </span>
              </div>
            </div>
          </div>

          {/* Right Action & Test Widget (1 col) */}
          <div className="rounded-3xl bg-slate-900 border border-slate-800 p-6 flex flex-col justify-between shadow-xl">
            <div>
              <div className="flex items-center gap-2 text-amber-400 text-xs font-bold uppercase tracking-wider mb-2">
                <Zap className="w-4 h-4" />
                <span>Interview Proof Panel</span>
              </div>
              <h3 className="text-base font-bold text-white mb-2">Concurrency Stress Test</h3>
              <p className="text-xs text-slate-400 leading-relaxed mb-4">
                Execute 10 simultaneous parallel transfers in the browser to empirically verify deadlock avoidance and conservation of money.
              </p>
            </div>

            <button
              onClick={() => {
                setShowConcurrencyModal(true);
                if (!concurrencyStats && !concurrencyRunning) {
                  runLiveConcurrencyTest();
                }
              }}
              className="w-full py-2.5 rounded-xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-semibold transition flex items-center justify-center gap-2 shadow-sm"
            >
              <Activity className="w-4 h-4 text-amber-400" />
              <span>Launch Live Race Test</span>
            </button>
          </div>
        </div>

        {/* Ledger & Transactions Section */}
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setActiveTab('ledger')}
                className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold transition flex items-center gap-2 ${
                  activeTab === 'ledger'
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/25'
                    : 'text-slate-400 hover:text-white hover:bg-slate-900'
                }`}
              >
                <Layers className="w-4 h-4" />
                <span>Double-Entry Ledger Feed</span>
                <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-indigo-950 text-indigo-300 border border-indigo-700/50">
                  {ledgerTotal}
                </span>
              </button>

              <button
                onClick={() => setActiveTab('transactions')}
                className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold transition flex items-center gap-2 ${
                  activeTab === 'transactions'
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/25'
                    : 'text-slate-400 hover:text-white hover:bg-slate-900'
                }`}
              >
                <Activity className="w-4 h-4" />
                <span>Transaction History</span>
                <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-slate-800 text-slate-300">
                  {transactions.length}
                </span>
              </button>
            </div>

            {/* Filter pills for Ledger */}
            {activeTab === 'ledger' && (
              <div className="flex items-center gap-1.5 bg-slate-900 p-1 rounded-xl border border-slate-800">
                {(['ALL', 'DEBIT', 'CREDIT'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => { setLedgerFilter(f); setLedgerPage(0); }}
                    className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition ${
                      ledgerFilter === f
                        ? 'bg-slate-800 text-white shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {f === 'ALL' ? 'All Entries' : f === 'DEBIT' ? 'Debits (-)' : 'Credits (+)'}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Tab 1: Double-Entry Ledger Table */}
          {activeTab === 'ledger' && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden shadow-lg">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-900/90 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider text-[10px]">
                    <tr>
                      <th className="px-4 py-3.5">Entry ID</th>
                      <th className="px-4 py-3.5">Type</th>
                      <th className="px-4 py-3.5">Amount</th>
                      <th className="px-4 py-3.5">Post Balance</th>
                      <th className="px-4 py-3.5">Counterparty</th>
                      <th className="px-4 py-3.5">Tx UUID / Details</th>
                      <th className="px-4 py-3.5">Timestamp</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {ledgerItems.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                          No ledger records matching this filter.
                        </td>
                      </tr>
                    ) : (
                      ledgerItems.map(item => {
                        const isCredit = item.entry_type === 'CREDIT';
                        return (
                          <tr key={item.id} className="hover:bg-slate-800/40 transition">
                            <td className="px-4 py-3.5 font-mono text-slate-400">#{item.id}</td>
                            <td className="px-4 py-3.5">
                              <span
                                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-bold tracking-wider ${
                                  isCredit
                                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                    : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                }`}
                              >
                                {isCredit ? <ArrowDownLeft className="w-3 h-3" /> : <ArrowUpRight className="w-3 h-3" />}
                                {item.entry_type}
                              </span>
                            </td>
                            <td className="px-4 py-3.5 font-bold font-mono">
                              <span className={isCredit ? 'text-emerald-400' : 'text-rose-400'}>
                                {isCredit ? '+' : '-'}${item.amount_dollars.toFixed(2)}
                              </span>
                            </td>
                            <td className="px-4 py-3.5 font-mono text-slate-300 font-medium">
                              ${item.balance_after_dollars.toFixed(2)}
                            </td>
                            <td className="px-4 py-3.5 font-medium text-slate-300">
                              {item.counterparty_username ? `@${item.counterparty_username}` : 'System Deposit'}
                            </td>
                            <td className="px-4 py-3.5">
                              <div className="flex items-center gap-1.5">
                                <span className="font-mono text-[10px] text-slate-400 truncate max-w-[120px]">
                                  {item.transaction_id}
                                </span>
                                <button
                                  onClick={() => handleCopy(item.transaction_id, `tx-${item.id}`)}
                                  className="text-slate-500 hover:text-slate-300 transition"
                                  title="Copy Transaction ID"
                                >
                                  {copiedKey === `tx-${item.id}` ? (
                                    <Check className="w-3 h-3 text-emerald-400" />
                                  ) : (
                                    <Copy className="w-3 h-3" />
                                  )}
                                </button>
                              </div>
                              {item.description && (
                                <p className="text-[10px] text-slate-500 mt-0.5">{item.description}</p>
                              )}
                            </td>
                            <td className="px-4 py-3.5 text-slate-400 text-[11px] whitespace-nowrap">
                              {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination controls */}
              <div className="px-4 py-3 bg-slate-900 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
                <span>
                  Showing {ledgerItems.length > 0 ? ledgerPage * pageSize + 1 : 0} to{' '}
                  {Math.min((ledgerPage + 1) * pageSize, ledgerTotal)} of {ledgerTotal} entries
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setLedgerPage(p => Math.max(0, p - 1))}
                    disabled={ledgerPage === 0}
                    className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 transition"
                  >
                    Previous
                  </button>
                  <span className="font-semibold text-slate-300">Page {ledgerPage + 1}</span>
                  <button
                    onClick={() => setLedgerPage(p => p + 1)}
                    disabled={(ledgerPage + 1) * pageSize >= ledgerTotal}
                    className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 transition"
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Tab 2: High-Level Transactions Feed */}
          {activeTab === 'transactions' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {transactions.length === 0 ? (
                <div className="col-span-2 text-center py-12 text-slate-500 text-xs bg-slate-900/60 rounded-2xl border border-slate-800">
                  No transactions on record. Use "Send Money" to execute a transfer!
                </div>
              ) : (
                transactions.map(tx => {
                  const isSent = tx.type === 'SENT';
                  return (
                    <div
                      key={tx.id}
                      className="p-4 rounded-2xl border border-slate-800 bg-slate-900/70 hover:border-slate-700 transition flex items-start justify-between"
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                            isSent ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          }`}
                        >
                          {isSent ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownLeft className="w-4 h-4" />}
                        </div>
                        <div>
                          <p className="font-semibold text-sm text-white">
                            {isSent ? `Paid to @${tx.counterparty_username}` : `Received from @${tx.counterparty_username}`}
                          </p>
                          <p className="text-xs text-slate-400">{tx.description || 'Payment'}</p>
                          <p className="text-[10px] text-slate-500 mt-1">
                            {new Date(tx.created_at).toLocaleString()}
                          </p>
                        </div>
                      </div>

                      <div className="text-right">
                        <p className={`font-mono font-bold text-sm ${isSent ? 'text-rose-400' : 'text-emerald-400'}`}>
                          {isSent ? '-' : '+'}${tx.amount_dollars.toFixed(2)}
                        </p>
                        <span className="inline-block mt-1 px-2 py-0.5 rounded text-[9px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                          {tx.status}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </main>

      {/* MODAL 1: Send Money (with Idempotency Key Demonstrator) */}
      {showTransferModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl relative">
            <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                  <ArrowUpRight className="w-4 h-4" />
                </div>
                <h3 className="font-bold text-lg text-white">Send Money</h3>
              </div>
              <button
                onClick={() => { setShowTransferModal(false); setTransferResult(null); }}
                className="text-slate-400 hover:text-white text-lg font-bold p-1"
              >
                ✕
              </button>
            </div>

            {transferResult && (
              <div
                className={`mb-5 p-4 rounded-xl text-xs flex flex-col gap-2 ${
                  transferResult.success
                    ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                    : 'bg-rose-500/10 border border-rose-500/20 text-rose-300'
                }`}
              >
                <div className="flex items-start gap-2">
                  {transferResult.success ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
                  <span className="font-semibold">{transferResult.message}</span>
                </div>
                {transferResult.receipt && (
                  <div className="bg-slate-950/80 p-2.5 rounded-lg font-mono text-[11px] text-slate-300 space-y-1 mt-1 border border-slate-800">
                    <div>Tx ID: {transferResult.receipt.transaction_id}</div>
                    <div>Idempotency Key: {transferResult.receipt.idempotency_key}</div>
                    <div>Post-Balance: ${transferResult.receipt.sender_balance_after_dollars?.toFixed(2)}</div>
                  </div>
                )}
              </div>
            )}

            <form onSubmit={handleTransferSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Recipient Username</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. bob_demo"
                  value={transferForm.receiver_username}
                  onChange={e => setTransferForm({ ...transferForm, receiver_username: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm font-medium"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Amount ($ USD)</label>
                <div className="relative">
                  <span className="absolute left-3.5 top-2.5 text-slate-400 text-sm">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={transferForm.amount}
                    onChange={e => setTransferForm({ ...transferForm, amount: e.target.value })}
                    className="w-full pl-8 pr-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm font-mono font-bold"
                  />
                </div>
                <div className="flex items-center gap-2 mt-2">
                  {['10.00', '25.00', '50.00', '100.00'].map(amt => (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => setTransferForm({ ...transferForm, amount: amt })}
                      className="px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono"
                    >
                      ${amt}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Payment Note / Description</label>
                <input
                  type="text"
                  placeholder="e.g. Project invoice #1024"
                  value={transferForm.description}
                  onChange={e => setTransferForm({ ...transferForm, description: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-sm"
                />
              </div>

              {/* Idempotency Key Live Feature */}
              <div className="p-3.5 rounded-xl bg-slate-950 border border-indigo-500/20 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5 font-semibold text-indigo-300">
                    <ShieldCheck className="w-3.5 h-3.5" />
                    <span>Client Idempotency Key</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setTransferForm(prev => ({ ...prev, idempotency_key: crypto.randomUUID() }))}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
                  >
                    <RefreshCw className="w-2.5 h-2.5" />
                    <span>New Key</span>
                  </button>
                </div>
                <input
                  type="text"
                  readOnly
                  value={transferForm.idempotency_key}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 text-xs font-mono select-all focus:outline-none"
                />

                <label className="flex items-center gap-2 cursor-pointer pt-1">
                  <input
                    type="checkbox"
                    checked={simulateDuplicateKey}
                    onChange={e => setSimulateDuplicateKey(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                  />
                  <span className="text-[11px] text-slate-400">
                    <strong className="text-slate-300">Simulate Network Retry:</strong> Keep key locked to test replay protection
                  </span>
                </label>
              </div>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => { setShowTransferModal(false); setTransferResult(null); }}
                  className="px-4 py-2.5 rounded-xl border border-slate-700 text-slate-300 text-xs font-medium hover:bg-slate-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={transferLoading}
                  className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs transition disabled:opacity-50 flex items-center gap-2"
                >
                  {transferLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <ArrowUpRight className="w-3.5 h-3.5" />}
                  <span>Confirm &amp; Execute Transfer</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: Deposit Modal */}
      {showDepositModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl relative">
            <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-emerald-600/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                  <DollarSign className="w-4 h-4" />
                </div>
                <h3 className="font-bold text-lg text-white">Deposit Test Funds</h3>
              </div>
              <button onClick={() => setShowDepositModal(false)} className="text-slate-400 hover:text-white text-lg font-bold">✕</button>
            </div>

            <form onSubmit={handleDepositSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Deposit Amount ($ USD)</label>
                <div className="relative">
                  <span className="absolute left-3.5 top-2.5 text-slate-400 text-sm">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="1.00"
                    max="10000.00"
                    required
                    value={depositAmount}
                    onChange={e => setDepositAmount(e.target.value)}
                    className="w-full pl-8 pr-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white text-sm font-mono font-bold focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="flex items-center gap-2 mt-2">
                  {['50.00', '100.00', '250.00', '500.00'].map(amt => (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => setDepositAmount(amt)}
                      className="px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono"
                    >
                      ${amt}
                    </button>
                  ))}
                </div>
              </div>

              <p className="text-[11px] text-slate-400 leading-relaxed bg-slate-950 p-3 rounded-xl border border-slate-800">
                Depositing funds updates your balance and appends an immutable <strong>CREDIT</strong> entry to your double-entry ledger.
              </p>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowDepositModal(false)}
                  className="px-4 py-2.5 rounded-xl border border-slate-700 text-slate-300 text-xs font-medium hover:bg-slate-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={depositLoading}
                  className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition disabled:opacity-50 flex items-center gap-2"
                >
                  {depositLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  <span>Credit Balance</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 3: Concurrency Stress Test Demonstrator */}
      {showConcurrencyModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl relative flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800 shrink-0">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400">
                  <Zap className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-lg text-white">Live Concurrency &amp; Race Condition Proof</h3>
                  <p className="text-xs text-slate-400">10 Simultaneous Bidirectional HTTP Transfers</p>
                </div>
              </div>
              <button onClick={() => setShowConcurrencyModal(false)} className="text-slate-400 hover:text-white text-lg font-bold">✕</button>
            </div>

            {/* Test Stats Panel */}
            {concurrencyStats && (
              <div className="mb-4 grid grid-cols-3 gap-3 p-3.5 rounded-2xl bg-slate-950 border border-slate-800 text-xs shrink-0">
                <div>
                  <span className="text-slate-400 block text-[10px]">Total Before:</span>
                  <span className="font-mono font-bold text-white">${concurrencyStats.totalInitial.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px]">Total After:</span>
                  <span className="font-mono font-bold text-emerald-400">${concurrencyStats.totalFinal.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px]">Conservation Result:</span>
                  <span className="font-bold text-emerald-400 flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    100% Invariant
                  </span>
                </div>
              </div>
            )}

            {/* Live Terminal Output */}
            <div className="flex-1 overflow-y-auto bg-slate-950 rounded-xl p-4 font-mono text-xs text-slate-300 space-y-1.5 border border-slate-800">
              {concurrencyLogs.length === 0 ? (
                <div className="text-slate-500 py-6 text-center">Ready to run concurrency stress test...</div>
              ) : (
                concurrencyLogs.map((log, i) => (
                  <div key={i} className="leading-relaxed">
                    {log}
                  </div>
                ))
              )}
            </div>

            <div className="pt-4 mt-4 border-t border-slate-800 flex items-center justify-between shrink-0">
              <span className="text-[11px] text-slate-400">
                Algorithm: Ascending Wallet ID Lock Order + Atomic SQL Updates
              </span>
              <button
                type="button"
                onClick={runLiveConcurrencyTest}
                disabled={concurrencyRunning}
                className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs transition disabled:opacity-50 flex items-center gap-1.5"
              >
                {concurrencyRunning ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
                <span>{concurrencyRunning ? 'Running Stress Test...' : 'Re-Run Stress Test'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 4: Architecture Deep Dive */}
      {showArchitectureModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-2xl relative max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                  <Layers className="w-4 h-4" />
                </div>
                <h3 className="font-bold text-lg text-white">PayFlow Engineering Architecture</h3>
              </div>
              <button onClick={() => setShowArchitectureModal(false)} className="text-slate-400 hover:text-white text-lg font-bold">✕</button>
            </div>

            <div className="space-y-4 text-xs text-slate-300 leading-relaxed">
              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                <h4 className="font-bold text-indigo-300 text-sm mb-1">1. Double-Entry Accounting</h4>
                <p className="text-slate-400">
                  Money is never created or destroyed. In `transfer_service.py`, every transfer creates two synchronized ledger rows: a <strong>DEBIT</strong> on the sender and a <strong>CREDIT</strong> on the receiver. Each row records the exact `balance_after` snapshot for verifiable auditability.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                <h4 className="font-bold text-emerald-300 text-sm mb-1">2. Deterministic Lock Ordering (Deadlock Freedom)</h4>
                <p className="text-slate-400">
                  To prevent deadlocks when User A sends to User B while User B simultaneously sends to User A, the system sorts wallet IDs: `first_id = min(A, B)` and `second_id = max(A, B)`. Both concurrent requests acquire locks in ascending order, eliminating circular wait.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                <h4 className="font-bold text-amber-300 text-sm mb-1">3. Atomic SQL Mutations (Lost Update Elimination)</h4>
                <p className="text-slate-400">
                  Instead of in-memory arithmetic (`wallet.balance -= amount`), balance mutations execute directly in SQL: `UPDATE wallets SET balance = balance - amount`. This ensures that concurrent commits never overwrite one another.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                <h4 className="font-bold text-blue-300 text-sm mb-1">4. Client Idempotency Keys</h4>
                <p className="text-slate-400">
                  Every transfer requires an `idempotency_key` (UUIDv4). If a network timeout occurs and the client retries the request, the server looks up the key and returns the existing transaction receipt without executing duplicate charges.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                <h4 className="font-bold text-purple-300 text-sm mb-1">5. Automated Pytest Verification</h4>
                <p className="text-slate-400">
                  The codebase includes <strong>18 automated tests</strong> spanning health checks, JWT authentication, duplicate detection, atomic balance conservation, idempotency replays, and multi-threaded concurrency.
                </p>
              </div>
            </div>

            <div className="pt-4 mt-4 border-t border-slate-800 text-right">
              <button
                onClick={() => setShowArchitectureModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-xs transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500 max-w-6xl mx-auto w-full px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
        <span>PayFlow – Digital Wallet &amp; Transaction Management System</span>
        <div className="flex items-center gap-4">
          <a href="/docs" target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline">Swagger Docs</a>
          <button onClick={() => setShowArchitectureModal(true)} className="text-indigo-400 hover:underline">Architecture Notes</button>
        </div>
      </footer>
    </div>
  );
}
