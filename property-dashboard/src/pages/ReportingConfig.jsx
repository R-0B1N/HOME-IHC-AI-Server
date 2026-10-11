import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  FileSpreadsheet, Download, Send, RefreshCw, CheckCircle2, 
  AlertCircle, Phone, Calendar, Clock, ShieldCheck, Zap
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export default function ReportingConfig() {
  const { isAdmin } = useAuth();
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [newAdminPhone, setNewAdminPhone] = useState('');

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE_URL}/settings/reporting-config`);
      setConfig(res.data);
    } catch (err) {
      console.error('Failed to fetch reporting config:', err);
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
        cron_schedule: config.cron_schedule,
        admin_numbers: config.admin_numbers,
        auto_dispatch_whatsapp: config.auto_dispatch_whatsapp
      };
      await axios.post(`${API_BASE_URL}/settings/reporting-config`, payload);
      setStatusMsg('Configuration saved successfully.');
      setTimeout(() => setStatusMsg(''), 4000);
    } catch (err) {
      console.error('Failed to save config:', err);
      alert('Failed to save reporting configuration.');
    } finally {
      setSaving(false);
    }
  };

  const [downloading, setDownloading] = useState({ buyer: false, owner: false });

  const handleTriggerReport = async (sendWhatsApp) => {
    setTriggering(true);
    setStatusMsg('');
    try {
      const res = await axios.post(`${API_BASE_URL}/settings/reporting-trigger?send_whatsapp=${sendWhatsApp}`);
      const r = res.data.result;
      setStatusMsg(
        `Reports generated successfully! Buyers: ${r.buyers_count || 0}, Properties: ${r.owners_count || 0}. ${
          sendWhatsApp ? 'Dispatched to Admin WhatsApp numbers.' : 'Available for immediate download.'
        }`
      );
      fetchConfig();
    } catch (err) {
      console.error('Failed to trigger report:', err);
      alert('Failed to trigger report generation.');
    } finally {
      setTriggering(false);
    }
  };

  const handleAddNumber = async () => {
    const clean = newAdminPhone.trim();
    if (!clean) return;
    if (config?.admin_numbers?.includes(clean)) {
      alert('Number already added.');
      return;
    }
    const updatedNumbers = [...(config?.admin_numbers || []), clean];
    const updatedConfig = {
      ...config,
      admin_numbers: updatedNumbers
    };
    setConfig(updatedConfig);
    setNewAdminPhone('');
    try {
      await axios.post(`${API_BASE_URL}/settings/reporting-config`, {
        enabled: updatedConfig.enabled,
        cron_schedule: updatedConfig.cron_schedule,
        admin_numbers: updatedNumbers,
        auto_dispatch_whatsapp: updatedConfig.auto_dispatch_whatsapp
      });
      setStatusMsg(`Added ${clean} and saved configuration.`);
      setTimeout(() => setStatusMsg(''), 3000);
    } catch (err) {
      console.error('Failed to auto-save after adding number:', err);
    }
  };

  const handleRemoveNumber = async (phoneToRemove) => {
    const updatedNumbers = (config?.admin_numbers || []).filter(p => p !== phoneToRemove);
    const updatedConfig = {
      ...config,
      admin_numbers: updatedNumbers
    };
    setConfig(updatedConfig);
    try {
      await axios.post(`${API_BASE_URL}/settings/reporting-config`, {
        enabled: updatedConfig.enabled,
        cron_schedule: updatedConfig.cron_schedule,
        admin_numbers: updatedNumbers,
        auto_dispatch_whatsapp: updatedConfig.auto_dispatch_whatsapp
      });
      setStatusMsg(`Removed ${phoneToRemove} and saved configuration.`);
      setTimeout(() => setStatusMsg(''), 3000);
    } catch (err) {
      console.error('Failed to auto-save after removing number:', err);
    }
  };

  const handleDownload = async (type) => {
    setDownloading(prev => ({ ...prev, [type]: true }));
    try {
      const res = await axios.get(`${API_BASE_URL}/settings/reporting-download/${type}`, {
        responseType: 'blob'
      });
      const blob = new Blob([res.data], { 
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' 
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${type === 'buyer' ? 'Buyer_Database' : 'Owner_Database'}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      fetchConfig();
    } catch (err) {
      console.error('Download failed:', err);
      alert('Failed to download report.');
    } finally {
      setDownloading(prev => ({ ...prev, [type]: false }));
    }
  };

  if (loading && !config) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8' }}>
        <RefreshCw className="spin" size={24} style={{ marginBottom: '8px' }} />
        <p>Loading Weekly Reporting Configuration...</p>
      </div>
    );
  }

  return (
    <div style={{ padding: '1rem 0' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.4rem', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FileSpreadsheet color="#10b981" size={26} /> Weekly Business Reporting Configuration
          </h2>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
            Configure Monday 09:00 MYT automated buyer & owner database spreadsheet generation and WhatsApp admin dispatches.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button 
            className="lux-btn-secondary"
            onClick={() => handleTriggerReport(false)}
            disabled={triggering}
            style={{ fontSize: '0.82rem', padding: '6px 14px' }}
          >
            {triggering ? 'Generating...' : '⚡ Generate Offline'}
          </button>
          <button 
            className="lux-btn-primary"
            onClick={() => handleTriggerReport(true)}
            disabled={triggering}
            style={{ fontSize: '0.82rem', padding: '6px 14px', background: '#10b981', borderColor: '#10b981' }}
          >
            <Send size={14} style={{ marginRight: '6px' }} />
            {triggering ? 'Dispatching...' : 'Generate & Dispatch to WhatsApp'}
          </button>
        </div>
      </div>

      {statusMsg && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          color: '#34d399',
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
        
        {/* Card 1: Configuration Form */}
        <div className="lux-card" style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '12px', padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f1f5f9', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Calendar size={18} color="#38bdf8" /> Automation Schedule & WhatsApp Dispatches
          </h3>

          <form onSubmit={handleSaveConfig}>
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                <input 
                  type="checkbox" 
                  checked={config?.enabled || false}
                  onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
                  style={{ width: '18px', height: '18px', accentColor: '#10b981' }}
                />
                <span style={{ color: '#f8fafc', fontWeight: 600, fontSize: '0.9rem' }}>
                  Enable Automated Weekly Reporting Engine
                </span>
              </label>
              <p style={{ color: '#64748b', fontSize: '0.75rem', marginLeft: '28px', marginTop: '2px' }}>
                Runs every Monday at 09:00 MYT (Celery Beat task `generate_and_send_weekly_reports`).
              </p>
            </div>

            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                <input 
                  type="checkbox" 
                  checked={config?.auto_dispatch_whatsapp || false}
                  onChange={(e) => setConfig({ ...config, auto_dispatch_whatsapp: e.target.checked })}
                  style={{ width: '18px', height: '18px', accentColor: '#38bdf8' }}
                />
                <span style={{ color: '#f8fafc', fontWeight: 600, fontSize: '0.9rem' }}>
                  Auto-Dispatch Document to Admin WhatsApp Numbers
                </span>
              </label>
              <p style={{ color: '#64748b', fontSize: '0.75rem', marginLeft: '28px', marginTop: '2px' }}>
                Sends Excel files natively via WhatsApp Cloud API / Chatwoot to configured admin lines.
              </p>
            </div>

            {/* Recipient Numbers List */}
            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ display: 'block', color: '#cbd5e1', fontSize: '0.82rem', fontWeight: 600, marginBottom: '6px' }}>
                Admin Recipient Numbers ({config?.admin_numbers?.length || 0})
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '8px' }}>
                {(config?.admin_numbers || []).map((phone) => (
                  <div 
                    key={phone}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid #334155',
                      padding: '6px 12px',
                      borderRadius: '6px',
                      fontSize: '0.85rem',
                      color: '#e2e8f0'
                    }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Phone size={14} color="#10b981" /> {phone}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveNumber(phone)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#ef4444',
                        cursor: 'pointer',
                        fontSize: '0.8rem',
                        fontWeight: 700
                      }}
                      title="Remove number"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>

              {/* Add New Number Input */}
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="text"
                  placeholder="+601xxxxxxxx"
                  value={newAdminPhone}
                  onChange={(e) => setNewAdminPhone(e.target.value)}
                  style={{
                    flex: 1,
                    background: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '6px',
                    padding: '6px 10px',
                    color: '#f8fafc',
                    fontSize: '0.85rem'
                  }}
                />
                <button
                  type="button"
                  onClick={handleAddNumber}
                  style={{
                    background: '#334155',
                    color: '#f8fafc',
                    border: 'none',
                    borderRadius: '6px',
                    padding: '6px 12px',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  + Add
                </button>
              </div>
            </div>

            <button 
              type="submit" 
              className="lux-btn-primary"
              disabled={saving}
              style={{ width: '100%', justifyContent: 'center' }}
            >
              {saving ? 'Saving...' : 'Save Configuration'}
            </button>
          </form>
        </div>

        {/* Card 2: Latest Generated Reports Download Center */}
        <div className="lux-card" style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '12px', padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f1f5f9', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Download size={18} color="#10b981" /> Download Generated Spreadsheets
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Buyer Report Card */}
            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid #334155',
              borderRadius: '8px',
              padding: '1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px'
            }}>
              <div>
                <strong style={{ color: '#38bdf8', fontSize: '0.92rem', display: 'block' }}>
                  📊 Buyer Database.xlsx
                </strong>
                <span style={{ color: '#64748b', fontSize: '0.78rem' }}>
                  {config?.latest_buyer_report || 'No file generated yet.'}
                </span>
              </div>
              <button
                onClick={() => handleDownload('buyer')}
                disabled={downloading.buyer}
                className="lux-btn-secondary"
                style={{ fontSize: '0.8rem', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Download size={14} /> {downloading.buyer ? 'Downloading...' : 'Download'}
              </button>
            </div>

            {/* Owner Report Card */}
            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid #334155',
              borderRadius: '8px',
              padding: '1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px'
            }}>
              <div>
                <strong style={{ color: '#a855f7', fontSize: '0.92rem', display: 'block' }}>
                  📑 Owner & Seller Database.xlsx
                </strong>
                <span style={{ color: '#64748b', fontSize: '0.78rem' }}>
                  {config?.latest_owner_report || 'Available for on-demand generation.'}
                </span>
              </div>
              <button
                onClick={() => handleDownload('owner')}
                disabled={downloading.owner}
                className="lux-btn-secondary"
                style={{ fontSize: '0.8rem', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Download size={14} /> {downloading.owner ? 'Downloading...' : 'Download'}
              </button>
            </div>

            {/* In-Chatwoot Command Reference Card */}
            <div style={{
              background: 'rgba(56, 189, 248, 0.06)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '8px',
              padding: '0.9rem',
              fontSize: '0.82rem',
              color: '#94a3b8'
            }}>
              <strong style={{ color: '#38bdf8', display: 'block', marginBottom: '4px' }}>
                💡 Chatwoot Private Note Commands:
              </strong>
              <ul style={{ margin: '0 0 0 16px', padding: 0, lineHeight: '1.6' }}>
                <li><code style={{ color: '#f8fafc', background: '#1e293b', padding: '1px 5px', borderRadius: '4px' }}>/report</code> — Generates both Excel spreadsheets and attaches them directly into the conversation private notes.</li>
                <li><code style={{ color: '#f8fafc', background: '#1e293b', padding: '1px 5px', borderRadius: '4px' }}>/report send</code> — Generates reports, attaches to private note, AND dispatches via WhatsApp to admin numbers.</li>
              </ul>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
