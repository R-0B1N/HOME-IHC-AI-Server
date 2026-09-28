import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Flame, Sun, Snowflake, Zap, Send, ShieldCheck, RefreshCw, 
  CheckCircle2, AlertTriangle, Clock, MessageSquare, Terminal
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export default function NurturingConfig() {
  const { isAdmin } = useAuth();
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [testPhone, setTestPhone] = useState('');
  const [forcedCadence, setForcedCadence] = useState('');

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE_URL}/settings/nurturing-config`);
      setConfig(res.data);
    } catch (err) {
      console.error('Failed to fetch nurturing config:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchConfig();
    }
  }, [isAdmin]);

  const handleSaveConfig = async (e) => {
    e.preventDefault();
    setSaving(true);
    setStatusMsg('');
    try {
      const payload = {
        enabled: config.enabled,
        staging_acceleration: config.staging_acceleration,
        meta_template_name: config.meta_template_name,
        hot_cadence_hours: parseFloat(config.hot_cadence_hours) || 24.0,
        warm_cadence_days: parseFloat(config.warm_cadence_days) || 5.0,
        cold_cadence_days: parseFloat(config.cold_cadence_days) || 14.0,
      };
      await axios.post(`${API_BASE_URL}/settings/nurturing-config`, payload);
      setStatusMsg('Nurturing configuration updated successfully.');
      setTimeout(() => setStatusMsg(''), 4000);
    } catch (err) {
      console.error('Failed to save nurturing config:', err);
      alert('Failed to save nurturing configuration.');
    } finally {
      setSaving(false);
    }
  };

  const handleTriggerCycle = async (phone = null, cadence = null) => {
    setTriggering(true);
    setStatusMsg('');
    try {
      let url = `${API_BASE_URL}/settings/nurturing-trigger`;
      const params = [];
      if (phone) params.push(`test_phone=${encodeURIComponent(phone)}`);
      if (cadence) params.push(`force_cadence=${encodeURIComponent(cadence)}`);
      if (params.length > 0) url += `?${params.join('&')}`;

      const res = await axios.post(url);
      const data = res.data;
      if (data.mode === 'single_customer') {
        const r = data.result;
        setStatusMsg(`Single Lead Result: Action='${r.action}'. Details: ${r.details}`);
      } else {
        const r = data.result;
        setStatusMsg(`Full Cycle Complete: ${r.nurtured_messages} messages sent, ${r.templates_dispatched} templates, ${r.private_notes} notes.`);
      }
    } catch (err) {
      console.error('Failed to trigger nurturing run:', err);
      const detail = err.response?.data?.detail || 'Failed to trigger nurturing run.';
      alert(detail);
    } finally {
      setTriggering(false);
    }
  };

  if (loading && !config) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8' }}>
        <RefreshCw className="spin" size={24} style={{ marginBottom: '8px' }} />
        <p>Loading Lead Nurturing Configuration...</p>
      </div>
    );
  }

  return (
    <div style={{ padding: '1rem 0' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.4rem', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Zap color="#f59e0b" size={26} /> Lead Nurturing & Follow-up Configuration
          </h2>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
            Object-Oriented Strategy Pattern Cadences, Meta 24-hour compliance window guard, and staging acceleration controls.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button 
            className="lux-btn-primary"
            onClick={() => handleTriggerCycle()}
            disabled={triggering}
            style={{ fontSize: '0.82rem', padding: '6px 14px', background: '#f59e0b', borderColor: '#f59e0b' }}
          >
            <RefreshCw size={14} style={{ marginRight: '6px' }} />
            {triggering ? 'Processing Cycle...' : 'Run Full Nurturing Scan'}
          </button>
        </div>
      </div>

      {statusMsg && (
        <div style={{
          background: 'rgba(245, 158, 11, 0.15)',
          border: '1px solid rgba(245, 158, 11, 0.4)',
          color: '#fbbf24',
          padding: '10px 16px',
          borderRadius: '8px',
          marginBottom: '1.5rem',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <CheckCircle2 size={16} /> {statusMsg}
        </div>
      )}

      {/* Grid Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '1.5rem' }}>
        
        {/* Card 1: Strategy Cadences Configuration */}
        <div className="lux-card" style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '12px', padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f1f5f9', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Clock size={18} color="#38bdf8" /> Temperature Strategy Cadences
          </h3>

          <form onSubmit={handleSaveConfig}>
            {/* Master Toggle */}
            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                <input 
                  type="checkbox" 
                  checked={config?.enabled || false}
                  onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
                  style={{ width: '18px', height: '18px', accentColor: '#10b981' }}
                />
                <span style={{ color: '#f8fafc', fontWeight: 600, fontSize: '0.9rem' }}>
                  Enable Automated Lead Follow-up Engine
                </span>
              </label>
              <p style={{ color: '#64748b', fontSize: '0.75rem', marginLeft: '28px', marginTop: '2px' }}>
                Scans customer last interaction timestamps hourly via Celery Beat.
              </p>
            </div>

            {/* Staging Acceleration Toggle */}
            <div style={{ 
              marginBottom: '1.25rem', 
              background: 'rgba(234, 179, 8, 0.08)', 
              border: '1px solid rgba(234, 179, 8, 0.3)', 
              padding: '10px 14px', 
              borderRadius: '8px' 
            }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                <input 
                  type="checkbox" 
                  checked={config?.staging_acceleration || false}
                  onChange={(e) => setConfig({ ...config, staging_acceleration: e.target.checked })}
                  style={{ width: '18px', height: '18px', accentColor: '#eab308' }}
                />
                <span style={{ color: '#fef08a', fontWeight: 700, fontSize: '0.88rem' }}>
                  ⚡ Staging Acceleration Mode (Testing Only)
                </span>
              </label>
              <p style={{ color: '#cbd5e1', fontSize: '0.76rem', marginLeft: '28px', marginTop: '4px' }}>
                Compresses timing cadences for staging verification: Hot triggers in 5–60 mins; Warm in 15–120 mins.
              </p>
            </div>

            {/* Cadence Inputs */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginBottom: '1.25rem' }}>
              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#ef4444', fontSize: '0.78rem', fontWeight: 700, marginBottom: '4px' }}>
                  <Flame size={13} /> Hot (Hours)
                </label>
                <input
                  type="number"
                  step="1"
                  value={config?.hot_cadence_hours || 24}
                  onChange={(e) => setConfig({ ...config, hot_cadence_hours: e.target.value })}
                  style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '6px 8px', color: '#f8fafc', fontSize: '0.85rem' }}
                />
              </div>

              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#eab308', fontSize: '0.78rem', fontWeight: 700, marginBottom: '4px' }}>
                  <Sun size={13} /> Warm (Days)
                </label>
                <input
                  type="number"
                  step="0.5"
                  value={config?.warm_cadence_days || 5}
                  onChange={(e) => setConfig({ ...config, warm_cadence_days: e.target.value })}
                  style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '6px 8px', color: '#f8fafc', fontSize: '0.85rem' }}
                />
              </div>

              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#38bdf8', fontSize: '0.78rem', fontWeight: 700, marginBottom: '4px' }}>
                  <Snowflake size={13} /> Cold (Days)
                </label>
                <input
                  type="number"
                  step="1"
                  value={config?.cold_cadence_days || 14}
                  onChange={(e) => setConfig({ ...config, cold_cadence_days: e.target.value })}
                  style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '6px 8px', color: '#f8fafc', fontSize: '0.85rem' }}
                />
              </div>
            </div>

            {/* Meta Template Name */}
            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ display: 'block', color: '#cbd5e1', fontSize: '0.82rem', fontWeight: 600, marginBottom: '6px' }}>
                Meta WhatsApp Re-engagement Template Name
              </label>
              <input
                type="text"
                value={config?.meta_template_name || 'lead_reengagement_utility'}
                onChange={(e) => setConfig({ ...config, meta_template_name: e.target.value })}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '7px 10px', color: '#f8fafc', fontSize: '0.85rem' }}
              />
              <p style={{ color: '#64748b', fontSize: '0.75rem', marginTop: '4px' }}>
                Required for contacts inactive &gt; 24 hours. Must be approved in Meta Business Manager.
              </p>
            </div>

            <button 
              type="submit" 
              className="lux-btn-primary"
              disabled={saving}
              style={{ width: '100%', justifyContent: 'center' }}
            >
              {saving ? 'Saving...' : 'Save Nurturing Settings'}
            </button>
          </form>
        </div>

        {/* Card 2: Manual Testing & Chatwoot Agent Controls */}
        <div className="lux-card" style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '12px', padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f1f5f9', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Terminal size={18} color="#10b981" /> Single Lead Testing & Simulation
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Single Lead Test Form */}
            <div style={{ background: 'rgba(255, 255, 255, 0.03)', border: '1px solid #334155', borderRadius: '8px', padding: '1rem' }}>
              <label style={{ display: 'block', color: '#cbd5e1', fontSize: '0.82rem', fontWeight: 600, marginBottom: '6px' }}>
                Target Lead Phone Number (e.g. Conversation 69 or Test Number)
              </label>
              <input
                type="tel"
                placeholder="+60128767882"
                value={testPhone}
                onChange={(e) => setTestPhone(e.target.value)}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '7px 10px', color: '#f8fafc', fontSize: '0.85rem', marginBottom: '10px' }}
              />

              <label style={{ display: 'block', color: '#cbd5e1', fontSize: '0.82rem', fontWeight: 600, marginBottom: '6px' }}>
                Cadence Strategy Override (Optional)
              </label>
              <select
                value={forcedCadence}
                onChange={(e) => setForcedCadence(e.target.value)}
                style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '7px 10px', color: '#f8fafc', fontSize: '0.85rem', marginBottom: '12px' }}
              >
                <option value="">Auto (Use Lead's Detected Temperature)</option>
                <option value="hot">🔥 Force HOT Cadence</option>
                <option value="warm">☀️ Force WARM Cadence</option>
                <option value="cold">❄️ Force COLD Cadence</option>
              </select>

              <button
                type="button"
                onClick={() => handleTriggerCycle(testPhone, forcedCadence)}
                disabled={triggering || !testPhone.trim()}
                className="lux-btn-primary"
                style={{ width: '100%', justifyContent: 'center', background: '#3b82f6', borderColor: '#3b82f6' }}
              >
                <Send size={14} style={{ marginRight: '6px' }} />
                {triggering ? 'Testing...' : 'Test Follow-Up on Lead'}
              </button>
            </div>

            {/* Chatwoot Commands Reference */}
            <div style={{
              background: 'rgba(245, 158, 11, 0.06)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              borderRadius: '8px',
              padding: '0.9rem',
              fontSize: '0.82rem',
              color: '#94a3b8'
            }}>
              <strong style={{ color: '#fbbf24', display: 'block', marginBottom: '4px' }}>
                💡 Chatwoot In-App Agent Commands:
              </strong>
              <ul style={{ margin: '0 0 0 16px', padding: 0, lineHeight: '1.6' }}>
                <li><code style={{ color: '#f8fafc', background: '#1e293b', padding: '1px 5px', borderRadius: '4px' }}>/nurture</code> — Evaluates lead's temperature and executes follow-up if due.</li>
                <li><code style={{ color: '#f8fafc', background: '#1e293b', padding: '1px 5px', borderRadius: '4px' }}>/nurture hot</code> — Forces an immediate Hot Lead follow-up re-engagement.</li>
                <li><code style={{ color: '#f8fafc', background: '#1e293b', padding: '1px 5px', borderRadius: '4px' }}>/nurture warm</code> — Forces a Warm Lead update follow-up.</li>
                <li><code style={{ color: '#f8fafc', background: '#1e293b', padding: '1px 5px', borderRadius: '4px' }}>/nurture cold</code> — Forces a Cold Lead re-engagement template.</li>
              </ul>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
