'use client';

import React, { useState, useEffect } from 'react';
import { 
  Users, Clock, Flame, Award, Video, FileText, Link as LinkIcon, 
  Lock, KeyRound, Send, ShieldAlert, CheckCircle2, AlertTriangle, 
  Settings, RefreshCw, Smartphone, Eye, EyeOff, Radio, Sparkles,
  ChevronRight, ArrowLeft, Bot, Globe, ShieldCheck, User
} from 'lucide-react';
import LiveVideoView from '@/components/parent/LiveVideoView';
import ParentAnalytics from '@/components/parent/ParentAnalytics';
import { pFetch, clearParentTokens, getParentAccessToken, storeParentTokens } from '@/lib/parent/parent-api';

export default function ParentDashboard() {
  // Authentication & Passcode ("Ask Pass") State
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [hasPinConfigured, setHasPinConfigured] = useState<boolean | null>(null);
  const [pinInput, setPinInput] = useState('');
  const [pinError, setPinError] = useState('');
  const [authLoading, setAuthLoading] = useState(false);

  // First-Run Setup Wizard State
  const [onboardingStep, setOnboardingStep] = useState<number>(1);
  const [showSetupWizard, setShowSetupWizard] = useState(false);

  // Wizard Config Form State
const [newPin, setNewPin] = useState('');
const [confirmPin, setConfirmPin] = useState('');
const [currentPinInput, setCurrentPinInput] = useState('');
  const [studentName, setStudentName] = useState('Alex');
  const [dailyGoalMinutes, setDailyGoalMinutes] = useState(60);
  const [alertStrictness, setAlertStrictness] = useState<'lenient' | 'normal' | 'strict'>('normal');

  const [telegramToken, setTelegramToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [telegramStatus, setTelegramStatus] = useState<string | null>(null);
  const [telegramTestSuccess, setTelegramTestSuccess] = useState(false);

  const [tunnelProvider, setTunnelProvider] = useState<'cloudflare' | 'ngrok'>('cloudflare');
  const [ngrokToken, setNgrokToken] = useState('');
  const [tunnelUrl, setTunnelUrl] = useState<string | null>(null);
  const [tunnelStatus, setTunnelStatus] = useState<string>('inactive');
  const [tunnelLoading, setTunnelLoading] = useState(false);

  // Dashboard Data State
  const [students, setStudents] = useState<any[]>([]);
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [selectedStudentForLive, setSelectedStudentForLive] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'analytics' | 'vault' | 'settings'>('overview');
  
  // Encrypted Vault State
const [vaultSnapshots, setVaultSnapshots] = useState<any[]>([]);
const [pendingVaultCount, setPendingVaultCount] = useState(0);
const [decryptedImage, setDecryptedImage] = useState<string | null>(null);
const [decryptedClip, setDecryptedClip] = useState<{ frames: string[]; fps: number } | null>(null);
  const [vaultLoading, setVaultLoading] = useState(false);

  const parentId = 'default';

  useEffect(() => {
    checkPinStatus();
    fetchTunnelStatus();
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      fetchDashboard();
      fetchTelegramConfig();
      fetchVaultSnapshots();
      fetchRecentIncidents();
      // Hydrate supervision rules into the Settings editor.
      pFetch(`/api/v1/parent/supervision-rules?parent_id=${parentId}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((rules) => {
          if (!rules) return;
          if (rules.student_name) setStudentName(rules.student_name);
          if (typeof rules.daily_goal_minutes === 'number') setDailyGoalMinutes(rules.daily_goal_minutes);
          const s = rules.alert_strictness;
          setAlertStrictness(s === 'gentle' ? 'lenient' : s === 'strict' ? 'strict' : 'normal');
        })
        .catch(() => {});
    }
  }, [isAuthenticated]);

  // Restore an existing parent session (token survives reloads within the tab;
  // pFetch transparently refreshes or re-locks on expiry).
  useEffect(() => {
    checkPinStatus();
    if (typeof window !== 'undefined' && getParentAccessToken()) {
      setIsAuthenticated(true);
    }
  }, []);

  const checkPinStatus = async () => {
    try {
      const res = await pFetch(`/api/v1/parent/auth/has-pin?parent_id=${parentId}`);
      if (res.ok) {
        const data = await res.json();
        setHasPinConfigured(data.has_pin);
      }
    } catch (err) {
      setHasPinConfigured(false);
    }
  };

  const handleVerifyPin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthLoading(true);
    setPinError('');
    try {
      const res = await pFetch('/api/v1/parent/auth/verify-pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: pinInput, parent_id: parentId }),
      });
      const data = await res.json();
      if (res.ok && data.access_token) {
        storeParentTokens(data.access_token, data.refresh_token);
        setIsAuthenticated(true);
        setPinInput('');
        // Encrypt any monitoring captures that were staged while locked out.
        fetch('/api/v1/parent/vault/seal', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${data.access_token}`,
          },
          body: JSON.stringify({ pin: pinInput }),
        }).catch(() => {});
      } else {
        setPinError(data.detail || 'Invalid Passcode PIN.');
      }
    } catch (err) {
      setPinError('Connection error. Please retry.');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSavePinStep = async () => {
    if (newPin.length < 4) {
      alert('PIN must be at least 4 digits.');
      return;
    }
    if (newPin !== confirmPin) {
      alert('PIN confirmation does not match.');
      return;
    }
    try {
      const res = await pFetch('/api/v1/parent/auth/set-pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: newPin, parent_id: parentId }),
      });
      if (res.ok) {
        setHasPinConfigured(true);
        // Auto-login so the freshly-setup parent lands inside the portal.
        try {
          const vres = await pFetch('/api/v1/parent/auth/verify-pin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin: newPin, parent_id: parentId }),
          });
          const vdata = await vres.json();
          if (vres.ok && vdata.access_token) {
            storeParentTokens(vdata.access_token, vdata.refresh_token);
            setIsAuthenticated(true);
            return;
          }
        } catch {
          /* fall through to wizard step 2 */
        }
        setOnboardingStep(2);
      } else {
        const errData = await res.json().catch(() => ({}));
        alert(errData.detail || 'Failed to save PIN.');
      }
    } catch (err) {
      alert('Failed to save PIN.');
    }
  };

  const fetchDashboard = async () => {
    try {
      const res = await pFetch(`/api/v1/parent/dashboard/${parentId}`);
      if (res.ok) {
        const data = await res.json();
        setStudents(data);
      }
    } catch (error) {
      console.error('Failed to fetch dashboard', error);
    }
  };

  const [recentIncidents, setRecentIncidents] = useState<any[]>([]);

  const fetchRecentIncidents = async () => {
    try {
      const res = await pFetch('/api/v1/parent/sessions/student-primary');
      if (res.ok) {
        const data = await res.json();
        setRecentIncidents(Array.isArray(data.recent_incidents) ? data.recent_incidents : []);
      }
    } catch (err) {
      console.error('Failed to fetch incidents', err);
    }
  };

  const fetchTelegramConfig = async () => {
    try {
      const res = await pFetch(`/api/v1/parent/telegram/config?parent_id=${parentId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.configured) {
          setTelegramChatId(data.chat_id || '');
          setTelegramTestSuccess(true);
        }
      }
    } catch (err) {
      console.error('Failed to fetch telegram config', err);
    }
  };

  const handleSaveTelegram = async () => {
    try {
      const res = await pFetch('/api/v1/parent/telegram/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bot_token: telegramToken,
          chat_id: telegramChatId,
          enabled: true,
          parent_id: parentId,
        }),
      });
      if (res.ok) {
        setTelegramStatus('Telegram credentials saved.');
        return true;
      }
    } catch (err) {
      setTelegramStatus('Failed to save Telegram credentials.');
    }
    return false;
  };

  const handleSendTelegramTest = async () => {
    if (!telegramToken || !telegramChatId) {
      alert('Please fill in both the Bot Token and Chat ID first.');
      return;
    }
    await handleSaveTelegram();
    setTelegramStatus('Sending test message to Telegram...');
    try {
      const res = await pFetch(`/api/v1/parent/telegram/test?parent_id=${parentId}`, { method: 'POST' });
      if (res.ok) {
        setTelegramStatus('✅ Test message successfully delivered to your Telegram!');
        setTelegramTestSuccess(true);
      } else {
        setTelegramStatus('❌ Delivery failed. Please verify Token and Chat ID.');
      }
    } catch (err) {
      setTelegramStatus('❌ Network error sending test message.');
    }
  };

  const handleSendTunnelLinkToTelegram = async () => {
    try {
      const res = await pFetch(`/api/v1/parent/telegram/send-link?parent_id=${parentId}&student_name=${studentName}`, { method: 'POST' });
      if (res.ok) {
        alert('🔗 Portal tunnel link dispatched to Telegram!');
      }
    } catch (err) {
      alert('Failed to send link to Telegram.');
    }
  };

  const fetchTunnelStatus = async () => {
    try {
      const res = await pFetch('/api/v1/parent/tunnel/status');
      if (res.ok) {
        const data = await res.json();
        setTunnelStatus(data.status);
        setTunnelUrl(data.url);
      }
    } catch (err) {
      console.error('Failed to fetch tunnel status', err);
    }
  };

  const handleToggleTunnel = async () => {
    setTunnelLoading(true);
    try {
      if (tunnelStatus === 'active') {
        await pFetch('/api/v1/parent/tunnel/stop', { method: 'POST' });
        setTunnelStatus('inactive');
        setTunnelUrl(null);
      } else {
        const res = await pFetch('/api/v1/parent/tunnel/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            provider: tunnelProvider, 
            ngrok_token: ngrokToken,
            port: 8001 
          }),
        });
        const data = await res.json();
        setTunnelStatus(data.status);
        setTunnelUrl(data.url);
      }
    } catch (err) {
      console.error('Tunnel toggle error', err);
    } finally {
      setTunnelLoading(false);
    }
  };

  const handleFinishOnboarding = async () => {
    await handleSaveTelegram();
    // Persist wizard step-4 supervision rules (server-side, drives warning gates).
    try {
      await pFetch('/api/v1/parent/supervision-rules', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          student_name: studentName,
          daily_goal_minutes: dailyGoalMinutes,
          // UI uses lenient|normal|strict; backend expects gentle|balanced|strict.
          alert_strictness:
            alertStrictness === 'lenient' ? 'gentle' : alertStrictness === 'strict' ? 'strict' : 'balanced',
          parent_id: parentId,
        }),
      });
    } catch (err) {
      console.warn('Failed to persist supervision rules', err);
    }
    setIsAuthenticated(true);
    setShowSetupWizard(false);
  };

  const fetchVaultSnapshots = async () => {
    try {
      const res = await pFetch('/api/v1/parent/vault/snapshots');
      if (res.ok) {
        const data = await res.json();
        // Backend returns { items: [...], pending_count: n }.
        setVaultSnapshots(Array.isArray(data) ? data : data.items ?? []);
        setPendingVaultCount(
          Array.isArray(data) ? 0 : typeof data.pending_count === 'number' ? data.pending_count : 0
        );
      }
    } catch (err) {
      console.error('Failed to fetch vault snapshots', err);
    }
  };

  const handleSealPendingVault = async () => {
    const pin = prompt('Enter your Parent Passcode to encrypt the pending monitoring captures:');
    if (!pin) return;
    setVaultLoading(true);
    try {
      const res = await pFetch('/api/v1/parent/vault/seal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Sealed ${data.sealed ?? 0} capture(s) into the encrypted vault.`);
        await fetchVaultSnapshots();
      } else {
        alert('Sealing failed. Please retry.');
      }
    } catch {
      alert('Error sealing pending captures.');
    } finally {
      setVaultLoading(false);
    }
  };

  const handleDecryptSnapshot = async (clipId: string) => {
    const pin = prompt('Enter Parent Passcode PIN to decrypt this local snapshot:');
    if (!pin) return;

    setVaultLoading(true);
    try {
      const res = await pFetch('/api/v1/parent/vault/decrypt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clip_id: clipId, pin }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.kind === 'clip' && Array.isArray(data.frames_base64)) {
          setDecryptedClip({ frames: data.frames_base64 as string[], fps: Number(data.fps ?? 5) });
          setDecryptedImage(null);
        } else {
          setDecryptedImage(`data:image/jpeg;base64,${data.image_base64}`);
          setDecryptedClip(null);
        }
      } else if (res.status === 403) {
        alert('Wrong Parent Passcode.');
      } else {
        alert('Decryption failed: item missing or corrupted.');
      }
    } catch (err) {
      alert('Error decrypting snapshot.');
    } finally {
      setVaultLoading(false);
    }
  };

  // --- 1. FIRST-RUN PARENT ONBOARDING SETUP WIZARD ---
  if (hasPinConfigured === false || showSetupWizard) {
    return (
      <div className="min-h-[90vh] flex items-center justify-center p-4 bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-950 text-slate-100">
        <div className="max-w-2xl w-full bg-slate-900/90 backdrop-blur-2xl rounded-3xl shadow-2xl border border-slate-800 p-8 space-y-6">
          
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-800 pb-5">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
                <Sparkles size={24} />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">AI Guru — Parent Setup Wizard</h2>
                <p className="text-xs text-slate-400">Configure Passcode PIN, Telegram alerts, and Outbound Tunnel</p>
              </div>
            </div>
            {hasPinConfigured && (
              <button 
                onClick={() => setShowSetupWizard(false)} 
                className="text-slate-400 hover:text-white text-xs px-3 py-1.5 rounded-xl border border-slate-800 hover:bg-slate-800"
              >
                Cancel
              </button>
            )}
          </div>

          {/* Stepper Progress Bar */}
          <div className="flex items-center justify-between px-2">
            {[
              { step: 1, label: "Passcode PIN", icon: KeyRound },
              { step: 2, label: "Telegram Bot", icon: Bot },
              { step: 3, label: "Tunnel Access", icon: Globe },
              { step: 4, label: "Supervision Rules", icon: ShieldCheck },
            ].map((item) => {
              const Icon = item.icon;
              const isDone = onboardingStep > item.step;
              const isCurrent = onboardingStep === item.step;
              return (
                <div key={item.step} className="flex items-center gap-2">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                    isDone 
                      ? "bg-green-500 text-white" 
                      : isCurrent 
                        ? "bg-blue-600 text-white shadow-lg shadow-blue-500/50" 
                        : "bg-slate-800 text-slate-400 border border-slate-700"
                  }`}>
                    {isDone ? <CheckCircle2 size={14} /> : item.step}
                  </div>
                  <span className={`text-xs font-semibold hidden sm:inline ${isCurrent ? "text-blue-400" : "text-slate-400"}`}>
                    {item.label}
                  </span>
                </div>
              );
            })}
          </div>

          {/* STEP 1: PASSCODE PIN */}
          {onboardingStep === 1 && (
            <div className="space-y-5 animate-in fade-in duration-300">
              <div className="p-4 bg-slate-800/50 rounded-2xl border border-slate-700/60 space-y-1">
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <Lock size={16} className="text-blue-400" />
                  <span>Create Parent Security Passcode</span>
                </h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  This PIN protects the Parent Portal so students cannot change rules, turn off monitoring, or view encrypted incident recordings.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">Enter 4–8 Digit PIN</label>
                  <input
                    type="password"
                    maxLength={8}
                    autoFocus
                    placeholder="e.g. 2468"
                    value={newPin}
                    onChange={(e) => setNewPin(e.target.value)}
                    className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-center text-2xl font-mono tracking-widest text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">Confirm PIN</label>
                  <input
                    type="password"
                    maxLength={8}
                    placeholder="Repeat PIN"
                    value={confirmPin}
                    onChange={(e) => setConfirmPin(e.target.value)}
                    className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-center text-2xl font-mono tracking-widest text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <button
                onClick={handleSavePinStep}
                disabled={!newPin || newPin.length < 4}
                className="w-full py-3.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-bold rounded-2xl transition-all shadow-lg shadow-blue-500/20 flex items-center justify-center gap-2"
              >
                <span>Save Passcode & Continue</span>
                <ChevronRight size={18} />
              </button>
            </div>
          )}

          {/* STEP 2: TELEGRAM BOT NOTIFICATIONS */}
          {onboardingStep === 2 && (
            <div className="space-y-5 animate-in fade-in duration-300">
              <div className="p-4 bg-slate-800/50 rounded-2xl border border-slate-700/60 space-y-2">
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <Send size={16} className="text-blue-400" />
                  <span>How to connect your Telegram in 2 minutes:</span>
                </h4>
                <ol className="text-xs text-slate-300 space-y-1.5 list-decimal pl-4">
                  <li>Open Telegram on your phone and search for <strong className="text-blue-400">@BotFather</strong>.</li>
                  <li>Send <code className="text-pink-300 bg-slate-900 px-1 py-0.5 rounded">/newbot</code> and copy the <strong>HTTP API Token</strong>.</li>
                  <li>Search for <strong className="text-blue-400">@userinfobot</strong> and click Start to get your <strong>Chat ID</strong>.</li>
                </ol>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Telegram Bot Token</label>
                  <input
                    type="password"
                    placeholder="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
                    value={telegramToken}
                    onChange={(e) => setTelegramToken(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Your Telegram Chat ID</label>
                  <input
                    type="text"
                    placeholder="e.g. 987654321"
                    value={telegramChatId}
                    onChange={(e) => setTelegramChatId(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                {telegramStatus && (
                  <p className="text-xs font-semibold text-blue-400 bg-slate-800/80 p-2.5 rounded-xl border border-slate-700">
                    {telegramStatus}
                  </p>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={handleSendTelegramTest}
                    className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-bold transition-colors flex items-center justify-center gap-1.5"
                  >
                    <Send size={14} />
                    <span>Send Test Alert to Phone</span>
                  </button>
                </div>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => setOnboardingStep(1)}
                  className="px-4 py-3 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-2xl text-xs font-bold"
                >
                  <ArrowLeft size={16} />
                </button>
                <button
                  onClick={() => setOnboardingStep(3)}
                  className="flex-1 py-3 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-2xl text-xs transition-all shadow-md flex items-center justify-center gap-1.5"
                >
                  <span>Continue to Tunnel Gateway</span>
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}

          {/* STEP 3: OUTBOUND ENCRYPTED TUNNEL */}
          {onboardingStep === 3 && (
            <div className="space-y-5 animate-in fade-in duration-300">
              <div className="p-4 bg-slate-800/50 rounded-2xl border border-slate-700/60 space-y-1">
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <Globe size={16} className="text-blue-400" />
                  <span>Choose Remote Access Tunnel</span>
                </h4>
                <p className="text-xs text-slate-400">
                  Enables you to supervise study sessions when away from home (on cellular data or office network) without opening router ports.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setTunnelProvider('cloudflare')}
                  className={`p-4 rounded-2xl border text-left transition-all ${
                    tunnelProvider === 'cloudflare'
                      ? 'border-blue-500 bg-blue-950/40 text-blue-300 shadow-inner'
                      : 'border-slate-700 bg-slate-800/40 text-slate-400'
                  }`}
                >
                  <span className="font-bold text-sm block text-white">Cloudflare Tunnel</span>
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    ✨ Recommended: 100% Free • No Account • Auto-Generated Link
                  </span>
                </button>

                <button
                  onClick={() => setTunnelProvider('ngrok')}
                  className={`p-4 rounded-2xl border text-left transition-all ${
                    tunnelProvider === 'ngrok'
                      ? 'border-blue-500 bg-blue-950/40 text-blue-300 shadow-inner'
                      : 'border-slate-700 bg-slate-800/40 text-slate-400'
                  }`}
                >
                  <span className="font-bold text-sm block text-white">Ngrok Gateway</span>
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    Requires Ngrok Free Account & Auth Token
                  </span>
                </button>
              </div>

              {tunnelProvider === 'ngrok' && (
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Ngrok Auth Token</label>
                  <input
                    type="password"
                    placeholder="Paste your 2xxxxxx ngrok token"
                    value={ngrokToken}
                    onChange={(e) => setNgrokToken(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              )}

              <div className="p-3.5 bg-slate-800/60 rounded-xl border border-slate-700 flex items-center justify-between">
                <div>
                  <span className="text-xs font-semibold text-slate-300">Tunnel Status: </span>
                  <span className="text-xs font-bold text-green-400 font-mono">{tunnelStatus.toUpperCase()}</span>
                  {tunnelUrl && <p className="text-[10px] text-blue-300 font-mono mt-0.5">{tunnelUrl}</p>}
                </div>
                <button
                  onClick={handleToggleTunnel}
                  disabled={tunnelLoading}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold"
                >
                  {tunnelLoading ? 'Starting...' : tunnelStatus === 'active' ? 'Restart' : 'Test & Start Tunnel'}
                </button>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => setOnboardingStep(2)}
                  className="px-4 py-3 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-2xl text-xs font-bold"
                >
                  <ArrowLeft size={16} />
                </button>
                <button
                  onClick={() => setOnboardingStep(4)}
                  className="flex-1 py-3 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-2xl text-xs transition-all shadow-md flex items-center justify-center gap-1.5"
                >
                  <span>Continue to Rules & Profile</span>
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}

          {/* STEP 4: SUPERVISION RULES & PROFILE */}
          {onboardingStep === 4 && (
            <div className="space-y-5 animate-in fade-in duration-300">
              <div className="p-4 bg-slate-800/50 rounded-2xl border border-slate-700/60 space-y-1">
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <User size={16} className="text-blue-400" />
                  <span>Student Profile & Supervision Preferences</span>
                </h4>
                <p className="text-xs text-slate-400">
                  Customize the student name and focus strictness level.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Student First Name</label>
                  <input
                    type="text"
                    value={studentName}
                    onChange={(e) => setStudentName(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Daily Target (Minutes)</label>
                  <input
                    type="number"
                    value={dailyGoalMinutes}
                    onChange={(e) => setDailyGoalMinutes(Number(e.target.value))}
                    className="w-full px-3.5 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-2">AI Nudge Strictness</label>
                <div className="grid grid-cols-3 gap-2">
                  {(['lenient', 'normal', 'strict'] as const).map((lvl) => (
                    <button
                      key={lvl}
                      onClick={() => setAlertStrictness(lvl)}
                      className={`py-2 px-3 rounded-xl border text-xs font-bold capitalize transition-all ${
                        alertStrictness === lvl
                          ? 'border-blue-500 bg-blue-600/30 text-white'
                          : 'border-slate-700 bg-slate-800/40 text-slate-400'
                      }`}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>
              </div>

              <div className="p-4 bg-green-950/30 border border-green-500/30 rounded-2xl flex items-center gap-3">
                <CheckCircle2 size={24} className="text-green-400 flex-shrink-0" />
                <div className="text-xs">
                  <strong className="text-green-300 block font-bold">All Set!</strong>
                  <p className="text-slate-300 mt-0.5">
                    Parent Passcode is active, Telegram notifications are ready, and the secure tunnel is configured.
                  </p>
                </div>
              </div>

              <button
                onClick={handleFinishOnboarding}
                className="w-full py-3.5 bg-green-600 hover:bg-green-500 text-white font-bold rounded-2xl transition-all shadow-lg shadow-green-500/20 flex items-center justify-center gap-2"
              >
                <Sparkles size={18} />
                <span>Finish Setup & Open Parent Portal</span>
              </button>
            </div>
          )}

        </div>
      </div>
    );
  }

  // --- 2. Passcode / "Ask Pass" Lock Screen (When PIN is configured but locked) ---
  if (!isAuthenticated) {
    return (
      <div className="min-h-[85vh] flex items-center justify-center p-4 bg-gradient-to-b from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-950">
        <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-2xl shadow-xl border border-gray-200 dark:border-gray-700 p-8 text-center">
          <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900/50 rounded-2xl flex items-center justify-center mx-auto mb-6 text-blue-600 dark:text-blue-400">
            <Lock size={32} />
          </div>

          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            AI Guru Parent Portal
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
            Enter your Parent Passcode PIN to access student monitoring.
          </p>

          <form onSubmit={handleVerifyPin} className="space-y-4">
            <div>
              <input
                type="password"
                maxLength={8}
                autoFocus
                placeholder="••••"
                value={pinInput}
                onChange={(e) => setPinInput(e.target.value)}
                className="w-full px-4 py-3.5 bg-gray-50 dark:bg-gray-700/50 border border-gray-300 dark:border-gray-600 rounded-xl text-center text-3xl tracking-widest font-mono text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
              />
            </div>

            {pinError && (
              <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-600 dark:text-red-400 flex items-center gap-2 justify-center">
                <AlertTriangle size={14} />
                <span>{pinError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={authLoading || !pinInput}
              className="w-full py-3.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold rounded-xl transition-all shadow-md flex items-center justify-center gap-2"
            >
              {authLoading ? <RefreshCw className="animate-spin" size={18} /> : <KeyRound size={18} />}
              <span>Unlock Parent Portal</span>
            </button>
          </form>

          <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 flex justify-between items-center text-xs">
            <button
              onClick={() => setShowSetupWizard(true)}
              className="text-blue-600 dark:text-blue-400 hover:underline"
            >
              Re-run Setup Wizard
            </button>
            <span className="text-gray-400 flex items-center gap-1">
              <ShieldAlert size={12} />
              Local Encryption Active
            </span>
          </div>
        </div>
      </div>
    );
  }

  // --- 3. Main Authenticated Parent Dashboard ---
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Header Bar */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white dark:bg-gray-800 p-6 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">AI Guru Parent Portal</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              Authenticated
            </span>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Real-time study monitoring, Telegram alerts, and encrypted local reporting
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {tunnelUrl && (
            <button
              onClick={handleSendTunnelLinkToTelegram}
              className="flex items-center gap-2 px-3.5 py-2 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 hover:bg-blue-100 border border-blue-200 dark:border-blue-800 rounded-xl text-sm font-medium transition-colors"
            >
              <Send size={16} />
              <span>Send Link to Telegram</span>
            </button>
          )}

          <button
            onClick={() => setShowSetupWizard(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-xl text-sm font-medium transition-colors"
          >
            <Settings size={16} />
            <span>Setup Wizard</span>
          </button>

          <button
            onClick={async () => {
            try {
              await pFetch('/api/v1/parent/auth/logout', { method: 'POST' });
            } catch { /* best-effort */ }
            clearParentTokens();
            setIsAuthenticated(false);
          }}
            className="flex items-center gap-2 px-4 py-2 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800/40 rounded-xl text-sm font-medium transition-colors"
          >
            <Lock size={16} />
            <span>Lock</span>
          </button>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700 pb-2">
        {(['overview', 'analytics', 'vault', 'settings'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-xl text-sm font-semibold capitalize transition-all ${
              activeTab === tab
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            {tab === 'vault' ? 'Encrypted Video Vault' : tab}
          </button>
        ))}
      </div>

      {/* TAB 1: OVERVIEW */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Outbound Tunnel Status Banner */}
          <div className="bg-gradient-to-r from-blue-500/10 via-purple-500/10 to-indigo-500/10 border border-blue-200 dark:border-blue-800/50 p-4 rounded-2xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-blue-600 text-white rounded-xl">
                <Radio size={20} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h4 className="font-semibold text-gray-900 dark:text-white text-sm">Remote Access Gateway</h4>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    tunnelStatus === 'active' ? 'bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300' : 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
                  }`}>
                    {tunnelStatus.toUpperCase()}
                  </span>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-0.5">
                  {tunnelUrl ? `Tunnel URL: ${tunnelUrl}` : 'Local network access only (No external open ports)'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={handleToggleTunnel}
                disabled={tunnelLoading}
                className="px-3.5 py-1.5 bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 border border-gray-300 dark:border-gray-600 rounded-lg text-xs font-semibold hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
              >
                {tunnelLoading ? 'Connecting...' : tunnelStatus === 'active' ? 'Stop Tunnel' : 'Start Cloudflare Tunnel'}
              </button>
            </div>
          </div>

          {/* Student Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {students.map((student) => (
              <div key={student.student_id} className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm flex flex-col justify-between">
                <div className="p-6 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 bg-blue-100 dark:bg-blue-900/60 rounded-2xl flex items-center justify-center text-xl font-bold text-blue-600 dark:text-blue-400 shadow-inner">
                        {student.name.charAt(0)}
                      </div>
                      <div>
                        <h3 className="font-bold text-lg text-gray-900 dark:text-white">{student.name}</h3>
                        <p className={`text-xs font-medium ${student.status === 'studying' ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-gray-500'}`}>
                          {student.status === 'studying'
                            ? (student.current_subject || 'Studying')
                            : 'Not studying right now'}
                        </p>
                      </div>
                    </div>

                    {student.status === 'studying' ? (
                      <span className="px-3 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-300 flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-green-500 animate-ping" />
                        Studying
                      </span>
                    ) : (
                      <span className="px-3 py-1 rounded-full text-xs font-semibold bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-gray-400" />
                        Offline
                      </span>
                    )}
                  </div>

                  {/* Telemetry Metrics Grid */}
                  <div className="grid grid-cols-2 gap-3 pt-2">
                    <div className="bg-gray-50 dark:bg-gray-700/40 p-3 rounded-xl border border-gray-100 dark:border-gray-700">
                      <div className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400 text-xs mb-1">
                        <Clock size={14} />
                        <span>Today's Time</span>
                      </div>
                      <div className="text-lg font-bold text-gray-900 dark:text-white">{student.today_study_time} mins</div>
                    </div>

                    <div className="bg-gray-50 dark:bg-gray-700/40 p-3 rounded-xl border border-gray-100 dark:border-gray-700">
                      <div className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400 text-xs mb-1">
                        <Flame size={14} className="text-orange-500" />
                        <span>Study Streak</span>
                      </div>
                      <div className="text-lg font-bold text-gray-900 dark:text-white">{student.streak} Days</div>
                    </div>

                    <div className="bg-gray-50 dark:bg-gray-700/40 p-3 rounded-xl border border-gray-100 dark:border-gray-700">
                      <div className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400 text-xs mb-1">
                        <Award size={14} className="text-purple-500" />
                        <span>Level {student.level}</span>
                      </div>
                      <div className="text-lg font-bold text-gray-900 dark:text-white">{student.xp} XP</div>
                    </div>

                    <div className="bg-gray-50 dark:bg-gray-700/40 p-3 rounded-xl border border-gray-100 dark:border-gray-700">
                      <div className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400 text-xs mb-1">
                        <Sparkles size={14} className="text-green-500" />
                        <span>Focus Score</span>
                      </div>
                      <div className="text-lg font-bold text-green-600 dark:text-green-400">{student.focus_score}%</div>
                    </div>
                  </div>
                </div>

                <div className="p-4 bg-gray-50 dark:bg-gray-800/80 border-t border-gray-100 dark:border-gray-700 flex gap-2">
                  <button
                    onClick={() => setActiveTab('analytics')}
                    className="flex-1 py-2.5 px-3 bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-xl text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 border border-gray-200 dark:border-gray-600"
                  >
                    <FileText size={14} />
                    <span>View Reports</span>
                  </button>

                  <button
                    onClick={() => setSelectedStudentForLive(student.name)}
                    className="flex-1 py-2.5 px-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <Video size={14} />
                    <span>Live Supervise</span>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Recent Distraction & Incident Timeline */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl p-6 border border-gray-200 dark:border-gray-700 shadow-sm">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <ShieldAlert className="text-blue-500" size={20} />
              <span>Real-Time Study Distraction & Stress Timeline</span>
            </h3>

            <div className="space-y-3">
              {recentIncidents.length === 0 ? (
                <div className="py-8 text-center text-gray-400">
                  <ShieldAlert size={30} className="mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No incidents recorded yet. Warnings from monitored sessions will appear here in real time.</p>
                </div>
              ) : (
                recentIncidents.map((item, idx) => {
                  const sev = String(item.severity || 'warning');
                  const color = sev === 'alert'
                    ? 'text-red-500 bg-red-50 dark:bg-red-900/20'
                    : sev === 'warning'
                      ? 'text-amber-500 bg-amber-50 dark:bg-amber-900/20'
                      : 'text-blue-500 bg-blue-50 dark:bg-blue-900/20';
                  return (
                <div key={idx} className="flex items-center justify-between p-3.5 bg-gray-50 dark:bg-gray-700/30 rounded-xl border border-gray-100 dark:border-gray-700">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${color}`}>
                      <ShieldAlert size={16} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-gray-900 dark:text-white">{item.event}</span>
                        <span className="text-xs font-mono text-gray-400">({item.time})</span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        {item.message || `Confidence ${Math.round((item.confidence || 0) * 100)}% · ${Math.round(item.duration_seconds || 0)}s`}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs px-2.5 py-1 rounded-full font-medium bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                    {sev === 'alert' ? 'Alert Sent' : sev === 'warning' ? 'Warning Logged' : 'Logged'}
                  </span>
                </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: ANALYTICS & REPORTS */}
      {activeTab === 'analytics' && (
        <div className="space-y-6">
          <ParentAnalytics studentId="student-primary" />
        </div>
      )}

      {/* TAB 3: ENCRYPTED VIDEO VAULT */}
      {activeTab === 'vault' && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl p-6 border border-gray-200 dark:border-gray-700 shadow-sm space-y-6">
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <Lock className="text-purple-500" size={20} />
              <span>AES-256-GCM Encrypted Local Video Vault</span>
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Incident frames are encrypted with your Parent Passcode. Students cannot open raw files on the computer.
            </p>
          </div>

          {/* Pending captures banner */}
          {pendingVaultCount > 0 && (
            <div className="flex items-center justify-between p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl">
              <div className="text-sm text-amber-800 dark:text-amber-300">
                <strong>{pendingVaultCount}</strong> monitoring capture(s) are staged and waiting to be encrypted.
              </div>
              <button
                onClick={handleSealPendingVault}
                disabled={vaultLoading}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white rounded-lg text-xs font-bold flex items-center gap-1.5"
              >
                <KeyRound size={14} /> Seal Now
              </button>
            </div>
          )}

          {/* Clip filmstrip view */}
          {decryptedClip && (
            <div className="bg-gray-900 rounded-xl p-4 border border-gray-700">
              <h4 className="text-sm font-semibold text-purple-300 mb-3">
                Decrypted Incident Clip · {decryptedClip.frames.length} frames @ {decryptedClip.fps} fps
              </h4>
              <div className="flex gap-2 overflow-x-auto pb-2">
                {decryptedClip.frames.map((f, i) => (
                  <img
                    key={i}
                    src={`data:image/jpeg;base64,${f}`}
                    alt={`Frame ${i + 1}`}
                    className="h-40 rounded-lg object-contain bg-black shrink-0"
                  />
                ))}
              </div>
              <button
                onClick={() => setDecryptedClip(null)}
                className="mt-3 px-4 py-1.5 bg-gray-800 hover:bg-gray-700 text-white rounded-lg text-xs font-medium"
              >
                Close Preview
              </button>
            </div>
          )}

          {decryptedImage && (
            <div className="bg-gray-900 rounded-xl p-4 inline-block border border-gray-700">
              <h4 className="text-sm font-semibold text-purple-300 mb-2">Decrypted Incident Snapshot Preview</h4>
              <img src={decryptedImage} alt="Decrypted Snapshot" className="max-h-80 rounded-xl object-contain" />
              <button
                onClick={() => setDecryptedImage(null)}
                className="mt-3 px-4 py-1.5 bg-gray-800 hover:bg-gray-700 text-white rounded-lg text-xs font-medium"
              >
                Close Preview
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {vaultSnapshots.length === 0 ? (
              <div className="col-span-full py-12 text-center text-gray-400">
                <Lock size={36} className="mx-auto mb-2 opacity-50" />
                <p className="text-sm">No encrypted incident clips captured in current session.</p>
              </div>
            ) : (
              vaultSnapshots.map((item) => (
                <div key={item.clip_id} className="p-4 bg-gray-50 dark:bg-gray-700/40 rounded-xl border border-gray-200 dark:border-gray-700 flex flex-col justify-between space-y-3">
                  <div>
                    <span className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 font-mono">
                      {item.event_type}
                    </span>
                    <p className="text-xs font-mono text-gray-500 mt-2 truncate">{item.clip_id}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{new Date(item.timestamp * 1000).toLocaleTimeString()}</p>
                  </div>
                  <button
                    onClick={() => handleDecryptSnapshot(item.clip_id)}
                    className="w-full py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <KeyRound size={14} />
                    <span>Decrypt & View</span>
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* TAB 4: PARENT SETTINGS */}
      {activeTab === 'settings' && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl p-6 border border-gray-200 dark:border-gray-700 shadow-sm space-y-6 max-w-3xl">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">Parent Security & Notification Configuration</h3>

          {/* Telegram Settings */}
          <div className="space-y-4 p-5 bg-gray-50 dark:bg-gray-700/30 rounded-xl border border-gray-200 dark:border-gray-700">
            <h4 className="font-semibold text-sm text-gray-900 dark:text-white flex items-center gap-2">
              <Send className="text-blue-500" size={16} />
              <span>Telegram Bot Notification Setup</span>
            </h4>
            <p className="text-xs text-gray-500">
              Create a free bot via @BotFather on Telegram, obtain your Bot Token and Chat ID to receive instant alerts and tunnel links.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Bot Token</label>
                <input
                  type="password"
                  placeholder="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
                  value={telegramToken}
                  onChange={(e) => setTelegramToken(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Your Chat ID</label>
                <input
                  type="text"
                  placeholder="e.g. 987654321"
                  value={telegramChatId}
                  onChange={(e) => setTelegramChatId(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {telegramStatus && (
                <p className="text-xs font-medium text-blue-600 dark:text-blue-400">{telegramStatus}</p>
              )}

              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleSaveTelegram}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold transition-colors"
                >
                  Save Telegram Setup
                </button>
                <button
                  onClick={handleSendTelegramTest}
                  className="px-4 py-2 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-800 dark:text-gray-200 rounded-xl text-xs font-semibold transition-colors"
                >
                  Send Test Alert
                </button>
              </div>
            </div>
          </div>

          {/* Change PIN Passcode (requires current PIN — server-enforced) */}
          <div className="space-y-4 p-5 bg-gray-50 dark:bg-gray-700/30 rounded-xl border border-gray-200 dark:border-gray-700">
            <h4 className="font-semibold text-sm text-gray-900 dark:text-white flex items-center gap-2">
              <KeyRound className="text-purple-500" size={16} />
              <span>Change Parent Passcode PIN</span>
            </h4>
            <input
              type="password"
              maxLength={8}
              placeholder="Current PIN"
              value={currentPinInput}
              onChange={(e) => setCurrentPinInput(e.target.value)}
              className="w-full px-3.5 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-xl text-sm font-mono text-center focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            <div className="grid grid-cols-2 gap-3">
              <input
                type="password"
                maxLength={8}
                placeholder="New PIN (4-8 digits)"
                value={newPin}
                onChange={(e) => setNewPin(e.target.value)}
                className="px-3.5 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-xl text-sm font-mono text-center focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <input
                type="password"
                maxLength={8}
                placeholder="Confirm New PIN"
                value={confirmPin}
                onChange={(e) => setConfirmPin(e.target.value)}
                className="px-3.5 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-xl text-sm font-mono text-center focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
            <button
              onClick={async () => {
                if (newPin.length < 4) { alert('PIN must be at least 4 digits.'); return; }
                if (newPin !== confirmPin) { alert('PIN confirmation does not match.'); return; }
                try {
                  const res = await pFetch('/api/v1/parent/auth/change-pin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pin: newPin, current_pin: currentPinInput, parent_id: parentId }),
                  });
                  if (res.ok) {
                    alert('Passcode updated.');
                    setCurrentPinInput(''); setNewPin(''); setConfirmPin('');
                  } else {
                    const errData = await res.json().catch(() => ({}));
                    alert(errData.detail || 'Failed to update passcode.');
                  }
                } catch { alert('Error updating passcode.'); }
              }}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold transition-colors"
            >
              Update Passcode PIN
            </button>
          </div>

          {/* Supervision Rules */}
          <div className="space-y-4 p-5 bg-gray-50 dark:bg-gray-700/30 rounded-xl border border-gray-200 dark:border-gray-700">
            <h4 className="font-semibold text-sm text-gray-900 dark:text-white flex items-center gap-2">
              <ShieldAlert className="text-blue-500" size={16} />
              <span>Supervision Rules</span>
            </h4>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">Student Name</span>
                <input
                  value={studentName}
                  onChange={(e) => setStudentName(e.target.value)}
                  maxLength={60}
                  className="w-full px-3 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">Daily Goal (minutes)</span>
                <input
                  type="number" min={10} max={600}
                  value={dailyGoalMinutes}
                  onChange={(e) => setDailyGoalMinutes(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>
            </div>
            <div>
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">Alert Strictness</span>
              <div className="flex gap-2">
                {(['lenient', 'normal', 'strict'] as const).map((lvl) => (
                  <button key={lvl} onClick={() => setAlertStrictness(lvl)}
                    className={`px-3 py-1.5 rounded-lg text-xs capitalize ${alertStrictness === lvl ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300'}`}>
                    {lvl === 'lenient' ? 'Gentle' : lvl === 'normal' ? 'Balanced' : 'Strict'}
                  </button>
                ))}
              </div>
            </div>
            <button
              onClick={async () => {
                try {
                  const res = await pFetch('/api/v1/parent/supervision-rules', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      student_name: studentName,
                      daily_goal_minutes: dailyGoalMinutes,
                      alert_strictness: alertStrictness === 'lenient' ? 'gentle' : alertStrictness === 'strict' ? 'strict' : 'balanced',
                      parent_id: parentId,
                    }),
                  });
                  alert(res.ok ? 'Supervision rules saved.' : 'Failed to save rules.');
                } catch { alert('Error saving rules.'); }
              }}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold transition-colors"
            >
              Save Supervision Rules
            </button>
          </div>
        </div>
      )}

      {/* MODAL: LIVE SUPERVISION STREAM */}
      {selectedStudentForLive && (
        <LiveVideoView
          studentName={selectedStudentForLive}
          onClose={() => setSelectedStudentForLive(null)}
        />
      )}
    </div>
  );
}
