import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  ChevronDown, ChevronRight, Bot, MessageSquareText, 
  ArrowRight, Database, Edit3, Check, AlertCircle, X, Save 
} from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const PERSONA_COLORS = {
  ROUTER: { bg: '#e8f0fe', border: '#4285f4', text: '#1a73e8', icon: '🧭' },
  BUYER: { bg: '#e6f4ea', border: '#34a853', text: '#137333', icon: '🛒' },
  SELLER: { bg: '#fef7e0', border: '#fbbc04', text: '#b06000', icon: '🏡' },
  TENANT: { bg: '#fce8e6', border: '#ea4335', text: '#c5221f', icon: '🔑' },
  LANDLORD: { bg: '#f3e8fd', border: '#9334e6', text: '#7627bb', icon: '🏢' },
  AGENT: { bg: '#e0f7fa', border: '#00acc1', text: '#00838f', icon: '🤝' },
  GLOBAL: { bg: '#f1f3f4', border: '#5f6368', text: '#3c4043', icon: '🌐' },
};

const DEFAULT_COLOR = { bg: '#f1f3f4', border: '#5f6368', text: '#3c4043', icon: '📋' };

function WorkflowViewer() {
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState('');
  const [personaFilter, setPersonaFilter] = useState('All');
  const [expandedPersonas, setExpandedPersonas] = useState({});

  // Editing modal state
  const [editingStep, setEditingStep] = useState(null);
  const [editFormData, setEditFormData] = useState({
    step_name: '',
    ai_action_instruction: '',
    message_template: '',
    next_step: '',
    expected_data_keys: ''
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchWorkflows();
  }, []);

  const fetchWorkflows = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`${API_BASE_URL}/admin/workflows`);
      setWorkflows(response.data);
      // Auto-expand all personas on first load
      const personas = [...new Set(response.data.map(w => w.persona_type))];
      const expanded = {};
      personas.forEach(p => { expanded[p] = true; });
      setExpandedPersonas(expanded);
    } catch (err) {
      console.error('Failed to fetch workflows:', err);
      setError('Failed to load workflow templates. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  const togglePersona = (persona) => {
    setExpandedPersonas(prev => ({
      ...prev,
      [persona]: !prev[persona]
    }));
  };

  const handleOpenEdit = (step) => {
    setEditingStep(step);
    setEditFormData({
      step_name: step.step_name || '',
      ai_action_instruction: step.ai_action_instruction || '',
      message_template: step.message_template || '',
      next_step: step.next_step !== null && step.next_step !== undefined ? step.next_step : '',
      expected_data_keys: (step.expected_data_keys || []).join(', ')
    });
  };

  const handleSaveStep = async (e) => {
    e.preventDefault();
    if (!editingStep) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        step_name: editFormData.step_name,
        ai_action_instruction: editFormData.ai_action_instruction,
        message_template: editFormData.message_template,
        next_step: editFormData.next_step !== '' ? parseInt(editFormData.next_step, 10) : null,
        expected_data_keys: editFormData.expected_data_keys.split(',').map(k => k.trim()).filter(Boolean)
      };

      await axios.put(`${API_BASE_URL}/admin/workflows/${editingStep.id}`, payload);
      setSuccessMsg(`Workflow step "${editFormData.step_name}" updated successfully.`);
      setEditingStep(null);
      fetchWorkflows();
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      console.error('Failed to update workflow step:', err);
      setError(err.response?.data?.detail || 'Failed to save workflow changes.');
    } finally {
      setSaving(false);
    }
  };

  const [seeding, setSeeding] = useState(false);

  const handleSeedWorkflows = async () => {
    if (!window.confirm("Are you sure you want to re-seed all default workflows? This will refresh all workflow templates to their standard 5-persona system definitions.")) {
      return;
    }
    setSeeding(true);
    setError(null);
    try {
      const res = await axios.post(`${API_BASE_URL}/admin/workflows/seed`);
      setSuccessMsg(res.data?.message || 'Successfully seeded all workflow templates.');
      fetchWorkflows();
      setTimeout(() => setSuccessMsg(''), 5000);
    } catch (err) {
      console.error('Failed to seed workflows:', err);
      setError(err.response?.data?.detail || 'Failed to seed workflow templates.');
    } finally {
      setSeeding(false);
    }
  };

  // Group workflows by persona_type
  const grouped = workflows.reduce((acc, step) => {
    if (!acc[step.persona_type]) acc[step.persona_type] = [];
    acc[step.persona_type].push(step);
    return acc;
  }, {});

  const personaTypes = Object.keys(grouped).sort((a, b) => {
    const order = ['ROUTER', 'BUYER', 'SELLER', 'TENANT', 'LANDLORD', 'AGENT', 'GLOBAL'];
    return (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b));
  });

  const filteredPersonas = personaFilter === 'All'
    ? personaTypes
    : personaTypes.filter(p => p === personaFilter);

  if (loading) {
    return (
      <div className="wf-loading">
        <div className="wf-spinner"></div>
        <p>Loading workflow templates…</p>
      </div>
    );
  }

  return (
    <div className="wf-container">
      {/* Header */}
      <div className="wf-header">
        <div className="wf-header-left">
          <h2>Workflow & Messaging Templates</h2>
          <span className="wf-count">{workflows.length} steps across {personaTypes.length} personas</span>
        </div>
        <div className="wf-header-right" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <select
            className="lux-select"
            value={personaFilter}
            onChange={(e) => setPersonaFilter(e.target.value)}
          >
            <option value="All">All Personas ({personaTypes.length})</option>
            {personaTypes.map(p => (
              <option key={p} value={p}>{(PERSONA_COLORS[p] || DEFAULT_COLOR).icon} {p}</option>
            ))}
          </select>
          <button className="lux-btn-secondary" onClick={fetchWorkflows} title="Refresh Workflows">
            ↻ Refresh
          </button>
          <button 
            className="lux-btn-primary" 
            onClick={handleSeedWorkflows} 
            disabled={seeding}
            title="Re-seed Default Workflows from System Definitions"
            style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', whiteSpace: 'nowrap' }}
          >
            {seeding ? '🌱 Seeding...' : '🌱 Re-seed Workflows'}
          </button>
        </div>
      </div>

      {/* Messages */}
      {successMsg && (
        <div className="alert-banner success" style={{ marginBottom: '1.25rem', textAlign: 'left' }}>
          <Check size={18} /> {successMsg}
        </div>
      )}
      {error && (
        <div className="alert-banner error" style={{ marginBottom: '1.25rem', textAlign: 'left' }}>
          <AlertCircle size={18} /> {error}
        </div>
      )}

      {/* Persona Groups */}
      {filteredPersonas.map(persona => {
        const steps = grouped[persona];
        const colors = PERSONA_COLORS[persona] || DEFAULT_COLOR;
        const isExpanded = expandedPersonas[persona];

        return (
          <div
            key={persona}
            className="wf-persona-group"
            style={{ borderLeft: `4px solid ${colors.border}` }}
          >
            <div
              className="wf-persona-header"
              onClick={() => togglePersona(persona)}
              style={{ backgroundColor: colors.bg, cursor: 'pointer' }}
            >
              <div className="wf-persona-title">
                {isExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
                <span className="wf-persona-icon">{colors.icon}</span>
                <h3 style={{ color: colors.text }}>{persona} Persona Workflow</h3>
                <span className="wf-step-count" style={{ color: colors.text }}>
                  {steps.length} step{steps.length !== 1 ? 's' : ''}
                </span>
              </div>
            </div>

            {isExpanded && (
              <div className="wf-steps-list">
                {steps.map((step) => (
                  <div key={step.id} className="wf-step-card">
                    <div className="wf-step-header">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                        <div className="wf-step-number" style={{ backgroundColor: colors.border }}>
                          {step.step_number}
                        </div>
                        <div className="wf-step-name">{step.step_name}</div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        {step.next_step !== null && (
                          <div className="wf-next-step">
                            <ArrowRight size={14} />
                            <span>→ Step {step.next_step}</span>
                          </div>
                        )}
                        <button 
                          className="lux-btn-secondary" 
                          style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
                          onClick={() => handleOpenEdit(step)}
                          title="Edit Message Template & Instruction"
                        >
                          <Edit3 size={14} /> Edit Message
                        </button>
                      </div>
                    </div>

                    <div className="wf-step-body">
                      <div className="wf-section">
                        <div className="wf-section-label">
                          <Bot size={14} /> AI Decision & Instruction
                        </div>
                        <div className="wf-ai-instruction">
                          {step.ai_action_instruction}
                        </div>
                      </div>

                      <div className="wf-section">
                        <div className="wf-section-label">
                          <MessageSquareText size={14} /> WhatsApp Message Template (Customer Facing)
                        </div>
                        <pre className="wf-message-template">
                          {step.message_template}
                        </pre>
                      </div>

                      {step.expected_data_keys && step.expected_data_keys.length > 0 && (
                        <div className="wf-section">
                          <div className="wf-section-label">
                            <Database size={14} /> Required Data Extraction Keys
                          </div>
                          <div className="wf-data-keys">
                            {step.expected_data_keys.map(key => (
                              <span key={key} className="wf-key-badge">{key}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Edit Workflow Step Modal */}
      {editingStep && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: '640px', textAlign: 'left' }}>
            <div className="modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Edit3 size={20} color="#d4af37" />
                <h2 style={{ margin: 0, fontSize: '1.2rem' }}>
                  Edit {editingStep.persona_type} • Step {editingStep.step_number}
                </h2>
              </div>
              <button className="close-btn" onClick={() => setEditingStep(null)}>✕</button>
            </div>

            <form onSubmit={handleSaveStep}>
              <div className="form-group" style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.35rem', fontSize: '0.85rem' }}>
                  Step Name
                </label>
                <input
                  type="text"
                  className="lux-search-input"
                  value={editFormData.step_name}
                  onChange={(e) => setEditFormData({ ...editFormData, step_name: e.target.value })}
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.35rem', fontSize: '0.85rem' }}>
                  AI Action Instruction
                </label>
                <textarea
                  className="lux-search-input"
                  style={{ minHeight: '80px', width: '100%', resize: 'vertical', fontFamily: 'inherit' }}
                  value={editFormData.ai_action_instruction}
                  onChange={(e) => setEditFormData({ ...editFormData, ai_action_instruction: e.target.value })}
                  required
                  placeholder="Instructions for the AI on how to handle this step..."
                />
              </div>

              <div className="form-group" style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.35rem', fontSize: '0.85rem' }}>
                  WhatsApp Message Template (Sent to Leads)
                </label>
                <textarea
                  className="lux-search-input"
                  style={{ minHeight: '140px', width: '100%', resize: 'vertical', fontFamily: 'SF Mono, Fira Code, monospace', fontSize: '0.85rem', lineHeight: '1.5' }}
                  value={editFormData.message_template}
                  onChange={(e) => setEditFormData({ ...editFormData, message_template: e.target.value })}
                  required
                  placeholder="Enter the template text with placeholders like {customer_name}, {property_title}..."
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1rem', marginBottom: '1.25rem' }}>
                <div className="form-group">
                  <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.35rem', fontSize: '0.85rem' }}>
                    Next Step Number
                  </label>
                  <input
                    type="number"
                    className="lux-search-input"
                    value={editFormData.next_step}
                    onChange={(e) => setEditFormData({ ...editFormData, next_step: e.target.value })}
                    placeholder="e.g. 2 (or leave empty)"
                  />
                </div>

                <div className="form-group">
                  <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.35rem', fontSize: '0.85rem' }}>
                    Expected Data Keys (Comma-separated)
                  </label>
                  <input
                    type="text"
                    className="lux-search-input"
                    value={editFormData.expected_data_keys}
                    onChange={(e) => setEditFormData({ ...editFormData, expected_data_keys: e.target.value })}
                    placeholder="budget_myr, preferred_location, acres"
                  />
                </div>
              </div>

              <div className="modal-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  className="lux-btn-secondary"
                  onClick={() => setEditingStep(null)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="lux-btn-primary"
                  disabled={saving}
                >
                  <Save size={16} /> {saving ? 'Saving Changes...' : 'Save Template'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default WorkflowViewer;
