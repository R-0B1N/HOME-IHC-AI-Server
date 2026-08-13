import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { ChevronDown, ChevronRight, Bot, MessageSquareText, ArrowRight, Database } from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://n8n.bentongland.com.my/api/v1';

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
  const [personaFilter, setPersonaFilter] = useState('All');
  const [expandedPersonas, setExpandedPersonas] = useState({});

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

  if (error) {
    return (
      <div className="wf-error">
        <p>{error}</p>
        <button className="btn-primary" onClick={fetchWorkflows}>Retry</button>
      </div>
    );
  }

  return (
    <div className="wf-container">
      <div className="wf-header">
        <div className="wf-header-left">
          <h2>Workflow Templates</h2>
          <span className="wf-count">{workflows.length} steps across {personaTypes.length} personas</span>
        </div>
        <div className="wf-header-right">
          <select
            className="form-select sort-select"
            value={personaFilter}
            onChange={(e) => setPersonaFilter(e.target.value)}
          >
            <option value="All">All Personas</option>
            {personaTypes.map(p => (
              <option key={p} value={p}>{(PERSONA_COLORS[p] || DEFAULT_COLOR).icon} {p}</option>
            ))}
          </select>
          <button className="btn-secondary" onClick={fetchWorkflows} title="Refresh">
            ↻ Refresh
          </button>
        </div>
      </div>

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
                <h3 style={{ color: colors.text }}>{persona}</h3>
                <span className="wf-step-count" style={{ color: colors.text }}>
                  {steps.length} step{steps.length !== 1 ? 's' : ''}
                </span>
              </div>
            </div>

            {isExpanded && (
              <div className="wf-steps-list">
                {steps.map((step, idx) => (
                  <div key={step.id} className="wf-step-card">
                    <div className="wf-step-header">
                      <div className="wf-step-number" style={{ backgroundColor: colors.border }}>
                        {step.step_number}
                      </div>
                      <div className="wf-step-name">{step.step_name}</div>
                      {step.next_step !== null && (
                        <div className="wf-next-step">
                          <ArrowRight size={14} />
                          <span>→ Step {step.next_step}</span>
                        </div>
                      )}
                    </div>

                    <div className="wf-step-body">
                      <div className="wf-section">
                        <div className="wf-section-label">
                          <Bot size={14} /> AI Instruction
                        </div>
                        <div className="wf-ai-instruction">
                          {step.ai_action_instruction}
                        </div>
                      </div>

                      <div className="wf-section">
                        <div className="wf-section-label">
                          <MessageSquareText size={14} /> Message Template
                        </div>
                        <pre className="wf-message-template">
                          {step.message_template}
                        </pre>
                      </div>

                      {step.expected_data_keys && step.expected_data_keys.length > 0 && (
                        <div className="wf-section">
                          <div className="wf-section-label">
                            <Database size={14} /> Expected Data Keys
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
    </div>
  );
}

export default WorkflowViewer;
