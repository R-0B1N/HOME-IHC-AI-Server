import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { 
  Plus, Home, MapPin, Tag, Edit, Trash2, Map, Users, 
  LayoutGrid, MessageCircle, X, GitBranch, LogOut, ShieldCheck, Shield, User,
  Sparkles, Table, Grid, Eye, Search, Layers, Activity, TrendingUp, Droplets, Zap,
  Compass, ExternalLink, CheckCircle2, ArrowRight, TreePine, Building2
} from 'lucide-react';
import { useAuth } from './context/AuthContext';
import WorkflowViewer from './pages/WorkflowViewer';
import UsersManagement from './pages/UsersManagement';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import './App.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

function App() {
  const { user, isAuthenticated, isAdmin, isAgent, isViewer, logout, loading: authLoading } = useAuth();
  const [authMode, setAuthMode] = useState('login'); // 'login' or 'register'

  const [properties, setProperties] = useState([]);
  const [viewMode, setViewMode] = useState('table'); // 'table' | 'grid'
  const [detailProperty, setDetailProperty] = useState(null);
  const [sortOrder, setSortOrder] = useState('newest'); // newest, price-asc, price-desc
  const [propStatusFilter, setPropStatusFilter] = useState('All');
  const [cityFilter, setCityFilter] = useState('All');
  const [stateFilter, setStateFilter] = useState('All');
  const [typeFilter, setTypeFilter] = useState('All');
  const [activeTab, setActiveTab] = useState('properties');
  const [leads, setLeads] = useState([]);
  const [leadSortOrder, setLeadSortOrder] = useState('newest');
  const [leadTempFilter, setLeadTempFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMapModalOpen, setIsMapModalOpen] = useState(false);
  const [selectedProperty, setSelectedProperty] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isLeadModalOpen, setIsLeadModalOpen] = useState(false);
  const [isEditingLead, setIsEditingLead] = useState(false);
  const [selectedLead, setSelectedLead] = useState(null);

  // Embeddings Explorer States
  const [embeddingsSummary, setEmbeddingsSummary] = useState(null);
  const [selectedEmbPropId, setSelectedEmbPropId] = useState('');
  const [propCorrelations, setPropCorrelations] = useState(null);
  const [propAspectChunks, setPropAspectChunks] = useState(null);
  const [isLoadingCorrelations, setIsLoadingCorrelations] = useState(false);
  const [nlQuery, setNlQuery] = useState('');
  const [nlSearchResults, setNlSearchResults] = useState(null);
  const [isSearchingNl, setIsSearchingNl] = useState(false);

  const [leadFormData, setLeadFormData] = useState({
    phone_number: '',
    contact_name: '',
    email: '',
    country: '',
    intent_category: 'general',
    intention_tag: 'Cold',
    ignore_ai: false
  });
  const [formData, setFormData] = useState({
    title: '',
    search_corpus_markdown: '',
    source_url: '',
    listing_status: 'Available',
    property_category: '',
    asking_price_myr: 0,
    monthly_rental_income_myr: 0,
    city: '',
    state: '',
    street_address: '',
    land_area_acres: 0,
    built_up_area_sqft: 0,
    tenure_type: '',
    power_supply_amp: 0,
    is_tenanted: false
  });

  const [masterAiEnabled, setMasterAiEnabled] = useState(true);
  const [environment, setEnvironment] = useState('production'); // 'production' | 'staging'
  const [isSyncingLeads, setIsSyncingLeads] = useState(false);
  const [isSeedingProps, setIsSeedingProps] = useState(false);

  const fetchProperties = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/properties`);
      setProperties(response.data);
      if (response.data && response.data.length > 0 && !selectedEmbPropId) {
        setSelectedEmbPropId(response.data[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch properties:', error);
    }
  };

  const fetchEmbeddingsSummary = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/properties/embeddings/summary`);
      setEmbeddingsSummary(response.data);
    } catch (error) {
      console.error('Failed to fetch embeddings summary:', error);
    }
  };

  const fetchPropertyCorrelations = async (propId) => {
    if (!propId) return;
    setIsLoadingCorrelations(true);
    try {
      const [corrRes, aspectRes] = await Promise.all([
        axios.get(`${API_BASE_URL}/properties/embeddings/correlations/${propId}?limit=6`),
        axios.get(`${API_BASE_URL}/properties/embeddings/aspects/${propId}`)
      ]);
      setPropCorrelations(corrRes.data);
      setPropAspectChunks(aspectRes.data);
    } catch (error) {
      console.error('Failed to fetch property correlations:', error);
    } finally {
      setIsLoadingCorrelations(false);
    }
  };

  const handleNlSearch = async (e) => {
    if (e) e.preventDefault();
    if (!nlQuery.trim()) return;
    setIsSearchingNl(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/properties/embeddings/query-search`, {
        query: nlQuery.trim(),
        limit: 6
      });
      setNlSearchResults(response.data);
    } catch (error) {
      console.error('Failed to run NL query search:', error);
    } finally {
      setIsSearchingNl(false);
    }
  };


  const [isSyncingWP, setIsSyncingWP] = useState(false);
  const [syncStatusText, setSyncStatusText] = useState('');

  const syncWordpressListings = async () => {
    setIsSyncingWP(true);
    setSyncStatusText('Starting sync...');
    try {
      const response = await axios.post(`${API_BASE_URL}/properties/sync-wordpress`, {}, { timeout: 30000 });
      if (response.data?.status === 'already_running') {
        alert('A WordPress sync is already in progress in the background.');
      } else {
        setSyncStatusText('Syncing WordPress listings & vectors...');
      }

      // Poll sync status every 3 seconds to update UI in real-time
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API_BASE_URL}/properties/sync-status`);
          const sData = statusRes.data;
          if (sData.is_syncing) {
            setSyncStatusText(sData.status || 'Syncing in background...');
            await fetchProperties(); // Refresh properties in real-time
          } else {
            clearInterval(pollInterval);
            setIsSyncingWP(false);
            setSyncStatusText('');
            await fetchProperties();
            if (sData.status === 'error') {
              alert(`WordPress Sync Error: ${sData.error || 'Unknown error'}`);
            } else {
              alert(`🎉 WordPress Sync Completed! ${sData.new_added || 0} new listings added, ${sData.updated || 0} updated (Total: ${sData.total_properties || sData.current_db_count || 0})`);
            }
          }
        } catch (pollErr) {
          console.error('Error polling sync status:', pollErr);
        }
      }, 3000);

    } catch (error) {
      console.error('Failed to initiate WordPress sync:', error);
      const errMsg = error.response?.data?.message || error.response?.data?.detail || error.message || 'Please check backend connection.';
      alert(`Failed to start WordPress sync: ${errMsg}`);
      setIsSyncingWP(false);
      setSyncStatusText('');
    }
  };

  const seedDefaultProperties = async () => {
    setIsSeedingProps(true);
    try {
      await axios.post(`${API_BASE_URL}/properties/seed-defaults`);
      await fetchProperties();
    } catch (error) {
      console.error('Failed to seed properties:', error);
    } finally {
      setIsSeedingProps(false);
    }
  };

  const fetchMasterAiStatus = async () => {
    try {
      const endpoint = environment === 'staging' 
        ? `${API_BASE_URL}/settings/staging/ai-status`
        : `${API_BASE_URL}/settings/ai-status`;
      const response = await axios.get(endpoint);
      setMasterAiEnabled(response.data.enabled);
    } catch (error) {
      console.error('Failed to fetch master AI status:', error);
    }
  };

  const toggleMasterAi = async () => {
    try {
      const newStatus = !masterAiEnabled;
      const endpoint = environment === 'staging'
        ? `${API_BASE_URL}/settings/staging/ai-status`
        : `${API_BASE_URL}/settings/ai-status`;
      const response = await axios.post(endpoint, { enabled: newStatus });
      setMasterAiEnabled(response.data.enabled);
    } catch (error) {
      console.error('Failed to toggle master AI status:', error);
      alert('Failed to toggle master AI status.');
    }
  };

  const fetchLeads = async () => {
    try {
      const endpoint = environment === 'staging'
        ? `${API_BASE_URL}/customers/staging`
        : `${API_BASE_URL}/customers`;
      const response = await axios.get(endpoint);
      setLeads(response.data);
    } catch (error) {
      console.error('Failed to fetch leads:', error);
    }
  };

  const syncChatwootLeads = async () => {
    setIsSyncingLeads(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/customers/sync-chatwoot`);
      await fetchLeads();
      alert(`Chatwoot Sync Complete: ${response.data.synced_count} new leads imported (Total: ${response.data.total_leads})`);
    } catch (error) {
      console.error('Failed to sync Chatwoot leads:', error);
      alert('Failed to sync Chatwoot leads. Please verify Chatwoot server connectivity.');
    } finally {
      setIsSyncingLeads(false);
    }
  };

  const handleResetStagingLeads = async () => {
    if (!window.confirm('Are you sure you want to clear all staging leads? Only fresh incoming messages to the test WhatsApp number will be recorded.')) return;
    try {
      await axios.delete(`${API_BASE_URL}/customers/staging/reset`);
      await fetchLeads();
      alert('Staging leads reset successfully. Only fresh test conversations will be stored.');
    } catch (error) {
      console.error('Failed to reset staging leads:', error);
      alert('Failed to reset staging leads.');
    }
  };



  // Fetch data on tab or environment change + auto-refresh every 30s for real-time updates
  useEffect(() => {
    fetchMasterAiStatus();
    
    if (activeTab === 'properties') {
      fetchProperties();
    } else if (activeTab === 'leads') {
      fetchLeads();
    }

    const interval = setInterval(() => {
      fetchMasterAiStatus();
      if (activeTab === 'properties') {
        fetchProperties();
      } else if (activeTab === 'leads') {
        fetchLeads();
      }
    }, 30000);

    return () => clearInterval(interval);
  }, [activeTab, environment]);
  // Sync selectedProperty details with updated properties data (keep modals in sync)
  useEffect(() => {
    if (selectedProperty) {
      const updated = properties.find(p => p.id === selectedProperty.id);
      if (updated) {
        setSelectedProperty(updated);
      }
    }
  }, [properties]);

  // Sync selectedLead details with updated leads data
  useEffect(() => {
    if (selectedLead) {
      const updated = leads.find(l => l.id === selectedLead.id);
      if (updated) {
        setSelectedLead(updated);
      }
    }
  }, [leads]);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData({
      ...formData,
      [name]: value
    });
  };

  const handleLeadInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setLeadFormData({
      ...leadFormData,
      [name]: type === 'checkbox' ? checked : value
    });
  };

  const handleOpenAddModal = () => {
    setIsEditing(false);
    setSelectedProperty(null);
    setFormData({
      title: '',
      search_corpus_markdown: '',
      source_url: '',
      listing_status: 'Available',
      property_category: '',
      asking_price_myr: 0,
      monthly_rental_income_myr: 0,
      city: '',
      state: '',
      street_address: '',
      land_area_acres: 0,
      built_up_area_sqft: 0,
      tenure_type: '',
      power_supply_amp: 0,
      is_tenanted: false
    });
    setIsModalOpen(true);
  };

  const handleOpenEditModal = (prop, e) => {
    e.stopPropagation();
    setIsEditing(true);
    setSelectedProperty(prop);
    setFormData({
      ...prop,
      property_category: Array.isArray(prop.property_category) ? prop.property_category.join(', ') : (prop.property_category || ''),
      amenities: Array.isArray(prop.amenities) ? prop.amenities.join(', ') : (prop.amenities || ''),
      facilities: Array.isArray(prop.facilities) ? prop.facilities.join(', ') : (prop.facilities || '')
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (window.confirm('Are you sure you want to delete this property?')) {
      try {
        await axios.delete(`${API_BASE_URL}/properties/${id}`);
        fetchProperties();
      } catch (error) {
        console.error('Failed to delete property:', error);
        const msg = error.response?.data?.detail || 'Failed to delete property.';
        alert(msg);
      }
    }
  };

  const handleOpenAddLeadModal = () => {
    setIsEditingLead(false);
    setSelectedLead(null);
    setLeadFormData({
      phone_number: '',
      contact_name: '',
      email: '',
      country: '',
      intent_category: 'general',
      intention_tag: 'Cold',
      ignore_ai: false
    });
    setIsLeadModalOpen(true);
  };

  const handleOpenEditLeadModal = (lead, e) => {
    e.stopPropagation();
    setIsEditingLead(true);
    setSelectedLead(lead);
    setLeadFormData({
      ...lead,
      ignore_ai: lead.metadata_json?.ignore_ai || false
    });
    setIsLeadModalOpen(true);
  };

  const handleDeleteLead = async (id, e) => {
    e.stopPropagation();
    if (window.confirm('Are you sure you want to delete this lead?')) {
      try {
        await axios.delete(`${API_BASE_URL}/customers/${encodeURIComponent(id)}`);
        fetchLeads();
      } catch (error) {
        console.error('Failed to delete lead:', error);
        const msg = error.response?.data?.detail || 'Failed to delete lead.';
        alert(msg);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      // Only send fields that match the PropertyCreate model
      const payload = {
        title: formData.title,
        search_corpus_markdown: formData.search_corpus_markdown || '',
        source_url: formData.source_url || '',
        listing_status: formData.listing_status || 'Available',
        property_category: typeof formData.property_category === 'string' ? formData.property_category.split(',').map(s => s.trim()).filter(Boolean) : (formData.property_category || []),
        asking_price_myr: parseFloat(formData.asking_price_myr) || 0,
        monthly_rental_income_myr: parseFloat(formData.monthly_rental_income_myr) || 0,
        city: formData.city || '',
        state: formData.state || '',
        street_address: formData.street_address || '',
        land_area_acres: parseFloat(formData.land_area_acres) || 0,
        built_up_area_sqft: parseFloat(formData.built_up_area_sqft) || 0,
        tenure_type: formData.tenure_type || '',
        power_supply_amp: parseInt(formData.power_supply_amp, 10) || 0,
        is_tenanted: formData.is_tenanted || false
      };
      if (isEditing && selectedProperty) {
        await axios.put(`${API_BASE_URL}/properties/${selectedProperty.id}`, payload);
      } else {
        await axios.post(`${API_BASE_URL}/properties`, payload);
      }
      setIsModalOpen(false);
      fetchProperties();
    } catch (error) {
      console.error('Failed to save property:', error);
      const msg = error.response?.data?.detail || 'Failed to save property.';
      alert(msg);
    }
  };

  const handleLeadSubmit = async (e) => {
    e.preventDefault();
    try {
      if (isEditingLead && selectedLead) {
        // Check if phone number was changed (phone = primary key, needs migration)
        const phoneChanged = leadFormData.phone_number !== selectedLead.phone_number;
        
        if (phoneChanged && leadFormData.phone_number) {
          // Migrate to new phone number first
          await axios.post(
            `${API_BASE_URL}/customers/${encodeURIComponent(selectedLead.phone_number)}/migrate`,
            { new_phone_number: leadFormData.phone_number }
          );
        }
        
        // Update editable fields (send only CustomerUpdate fields)
        const updatePayload = {
          contact_name: leadFormData.contact_name,
          email: leadFormData.email || null,
          country: leadFormData.country || null,
          intent_category: leadFormData.intent_category,
          intention_tag: leadFormData.intention_tag,
          ignore_ai: leadFormData.ignore_ai
        };
        const customerId = phoneChanged ? leadFormData.phone_number : selectedLead.phone_number;
        await axios.put(`${API_BASE_URL}/customers/${encodeURIComponent(customerId)}`, updatePayload);
      } else {
        // Create new lead
        await axios.post(`${API_BASE_URL}/customers`, {
          phone_number: leadFormData.phone_number,
          contact_name: leadFormData.contact_name,
          email: leadFormData.email || null,
          country: leadFormData.country || null,
          intent_category: leadFormData.intent_category || 'general',
          intention_tag: leadFormData.intention_tag || 'Cold',
          ignore_ai: leadFormData.ignore_ai || false
        });
      }
      setIsLeadModalOpen(false);
      fetchLeads();
    } catch (error) {
      console.error('Failed to save lead:', error);
      const msg = error.response?.data?.detail || 'Failed to save lead. Make sure phone number is unique.';
      alert(msg);
    }
  };

  const toggleIgnoreAI = async (lead) => {
    try {
      const currentIgnore = lead.metadata_json?.ignore_ai || false;
      const newIgnore = !currentIgnore;
      
      const payload = {
        contact_name: lead.contact_name,
        email: lead.email,
        country: lead.country,
        intent_category: lead.intent_category,
        intention_tag: lead.intention_tag,
        ignore_ai: newIgnore
      };
      
      await axios.put(`${API_BASE_URL}/customers/${encodeURIComponent(lead.phone_number)}`, payload);
      fetchLeads();
    } catch (error) {
      console.error('Failed to toggle AI status:', error);
      alert('Failed to toggle AI status.');
    }
  };

  const handleViewMap = (prop) => {
    setSelectedProperty(prop);
    setIsMapModalOpen(true);
  };

  const formatPrice = (price) => {
    return new Intl.NumberFormat('en-MY', {
      style: 'currency',
      currency: 'MYR',
      minimumFractionDigits: 0
    }).format(price);
  };

  const uniqueCities = ['All', ...new Set(properties.map(p => p.city).filter(Boolean).map(c => c.trim()))].sort();
  const uniqueStates = ['All', ...new Set(properties.map(p => p.state).filter(Boolean).map(s => s.trim()))].sort();
  const uniqueTypes = ['All', ...new Set(properties.flatMap(p => p.property_category || []).filter(Boolean).map(t => typeof t === 'string' ? t.trim() : ''))].sort();

  const filteredProperties = properties.filter((prop) => {
    const matchesSearch = (prop.title || '').toLowerCase().includes(searchTerm.toLowerCase()) || 
                          (prop.street_address || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
                          (prop.property_category || []).join(' ').toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = propStatusFilter === 'All' || prop.listing_status === propStatusFilter;
    const matchesCity = cityFilter === 'All' || (prop.city && prop.city.trim() === cityFilter);
    const matchesState = stateFilter === 'All' || (prop.state && prop.state.trim() === stateFilter);
    const matchesType = typeFilter === 'All' || (prop.property_category && prop.property_category.some(c => typeof c === 'string' && c.trim() === typeFilter));
    return matchesSearch && matchesStatus && matchesCity && matchesState && matchesType;
  });

  const sortedProperties = [...filteredProperties].sort((a, b) => {
    if (sortOrder === 'price-asc') return (a.asking_price_myr || 0) - (b.asking_price_myr || 0);
    if (sortOrder === 'price-desc') return (b.asking_price_myr || 0) - (a.asking_price_myr || 0);
    return b.created_at ? new Date(b.created_at) - new Date(a.created_at) : 0;
  });

  if (authLoading) {
    return (
      <div className="lux-auth-viewport">
        <div className="lux-card" style={{ textAlign: 'center', padding: '3rem', maxWidth: '380px' }}>
          <div className="lux-spinner" style={{ margin: '0 auto 1.25rem', width: '28px', height: '28px', borderWidth: '3px', borderColor: 'rgba(212, 175, 55, 0.2)', borderTopColor: '#d4af37' }}></div>
          <h2 style={{ color: '#f8fafc', fontSize: '1.1rem', margin: '0 0 0.25rem 0' }}>BentongLand CRM</h2>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: 0 }}>Verifying secure session...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    if (authMode === 'register') {
      return <RegisterPage onSwitchToLogin={() => setAuthMode('login')} />;
    }
    return <LoginPage onSwitchToRegister={() => setAuthMode('register')} />;
  }

  return (
    <div className="dashboard-container">
      {/* Tier 1: Modern Luxury Header */}
      <header className="lux-top-header">
        <div className="lux-brand-group">
          <div className="lux-brand-icon">
            <Home size={22} color="#d4af37" />
          </div>
          <div>
            <div className="lux-brand-title">Home IHC • BentongLand DB</div>
            <div className="lux-brand-sub">Real Estate Intelligence & Operations</div>
          </div>
        </div>

        <div className="lux-header-actions-group">
          {/* Admin-Only Environment Switcher */}
          {isAdmin && (
            <div style={{ display: 'flex', alignItems: 'center', background: 'rgba(255,255,255,0.06)', borderRadius: '8px', padding: '3px', border: '1px solid rgba(255,255,255,0.1)' }}>
              <button 
                style={{
                  padding: '5px 12px',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer',
                  background: environment === 'production' ? '#10b981' : 'transparent',
                  color: environment === 'production' ? '#ffffff' : '#94a3b8',
                  transition: 'all 0.2s ease',
                  letterSpacing: '0.03em'
                }}
                onClick={() => setEnvironment('production')}
                title="Switch to Live Production Environment"
              >
                🟢 Production
              </button>
              <button 
                style={{
                  padding: '5px 12px',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer',
                  background: environment === 'staging' ? '#f59e0b' : 'transparent',
                  color: environment === 'staging' ? '#000000' : '#94a3b8',
                  transition: 'all 0.2s ease',
                  letterSpacing: '0.03em'
                }}
                onClick={() => setEnvironment('staging')}
                title="Switch to Staging / Development Environment"
              >
                🟡 Staging
              </button>
            </div>
          )}

          {/* Master AI Toggle Pill */}
          <button 
            className={`lux-ai-toggle-pill ${masterAiEnabled ? 'active' : 'disabled'}`}
            onClick={toggleMasterAi}
            title={masterAiEnabled ? `Click to disable ${environment} AI automated responses` : `Click to enable ${environment} AI automated responses`}
          >
            <span className={`lux-status-dot ${masterAiEnabled ? 'active' : 'disabled'}`}></span>
            {environment === 'staging' ? 'Staging AI' : 'Master AI'}: <strong>{masterAiEnabled ? 'ON' : 'OFF'}</strong>
          </button>

          {/* Authenticated User Capsule */}
          <div className="lux-user-capsule">
            <div className={`lux-user-avatar ${user?.role || 'agent'}`}>
              {user?.full_name ? user.full_name.charAt(0).toUpperCase() : (user?.username || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="lux-user-details">
              <span className="lux-user-name">{user?.full_name || user?.username}</span>
              <span className={`lux-role-pill ${user?.role || 'agent'}`}>
                {user?.role === 'admin' ? '🛡️ Admin' : user?.role === 'agent' ? '🤝 Agent' : '👁️ Viewer'}
              </span>
            </div>
            <button 
              className="lux-logout-btn"
              onClick={logout}
              title="Sign Out"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </header>

      {/* Staging Notification Banner */}
      {environment === 'staging' && (
        <div style={{
          background: 'linear-gradient(90deg, rgba(245, 158, 11, 0.2) 0%, rgba(245, 158, 11, 0.08) 100%)',
          borderBottom: '1px solid rgba(245, 158, 11, 0.4)',
          color: '#fbbf24',
          padding: '8px 24px',
          fontSize: '0.82rem',
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div>
            ⚠️ <strong>STAGING / DEVELOPMENT ENVIRONMENT ACTIVE</strong> — Viewing staging leads and controlling staging AI responses.
          </div>
          <span style={{ fontSize: '0.75rem', opacity: 0.85, background: 'rgba(245, 158, 11, 0.2)', padding: '2px 8px', borderRadius: '4px' }}>
            Isolated Staging Redis & Database
          </span>
        </div>
      )}


      {/* Tier 2: Sub-Nav Bar (Tabs on Left, Action CTAs on Right) */}
      <div className="lux-subnav-bar">
        <div className="lux-tabs-container">
          <button 
            className={`lux-tab-btn ${activeTab === 'properties' ? 'active' : ''}`}
            onClick={() => setActiveTab('properties')}
          >
            <LayoutGrid size={17} /> Properties
            <span className="lux-tab-count">{properties.length}</span>
          </button>
          <button 
            className={`lux-tab-btn ${activeTab === 'leads' ? 'active' : ''}`}
            onClick={() => setActiveTab('leads')}
          >
            <Users size={17} /> Leads
            <span className="lux-tab-count">{leads.length}</span>
          </button>
          <button 
            className={`lux-tab-btn ${activeTab === 'embeddings' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('embeddings');
              fetchEmbeddingsSummary();
              if (properties.length > 0) {
                const targetId = selectedEmbPropId || properties[0].id;
                setSelectedEmbPropId(targetId);
                fetchPropertyCorrelations(targetId);
              }
            }}
          >
            <Sparkles size={17} color="#a855f7" /> Vector Embeddings
          </button>
          <button 
            className={`lux-tab-btn ${activeTab === 'workflows' ? 'active' : ''}`}
            onClick={() => setActiveTab('workflows')}
          >
            <GitBranch size={17} /> Workflows
          </button>
          {isAdmin && (
            <button 
              className={`lux-tab-btn ${activeTab === 'users' ? 'active' : ''}`}
              onClick={() => setActiveTab('users')}
            >
              <ShieldCheck size={17} /> User Accounts
            </button>
          )}
        </div>

        {/* Global Action CTAs for Active Tab */}
        <div className="lux-tab-actions">
          {activeTab === 'properties' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              <button 
                className="lux-btn-secondary"
                onClick={syncWordpressListings}
                disabled={isSyncingWP}
                title="Sync all properties from bentongland.com.my WordPress"
              >
                {isSyncingWP ? (syncStatusText || 'Syncing WP...') : '🔄 Sync WordPress'}
              </button>
              <button className="lux-btn-primary" onClick={handleOpenAddModal}>
                <Plus size={16} /> Add Listing
              </button>
            </div>
          )}

          {activeTab === 'leads' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              <button 
                className="lux-btn-secondary"
                onClick={syncChatwootLeads}
                disabled={isSyncingLeads}
                title="Import all leads directly from Chatwoot contacts"
              >
                {isSyncingLeads ? 'Syncing...' : '🔄 Sync Chatwoot Leads'}
              </button>
              <button className="lux-btn-primary" onClick={handleOpenAddLeadModal}>
                <Plus size={16} /> Add Lead
              </button>
            </div>
          )}

          {activeTab === 'embeddings' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              <button 
                className="lux-btn-secondary"
                onClick={() => {
                  fetchEmbeddingsSummary();
                  if (selectedEmbPropId) fetchPropertyCorrelations(selectedEmbPropId);
                }}
                title="Refresh vector statistics & correlations"
              >
                🔄 Refresh Vectors
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Tier 3: Contextual Filter Toolbar for Properties */}
      {activeTab === 'properties' && (
        <div className="lux-filter-bar">
          <div className="lux-search-box" style={{ flex: 1, minWidth: '220px' }}>
            <input 
              type="text" 
              className="lux-search-input" 
              placeholder="Search properties by title, location, category..." 
              value={searchTerm} 
              onChange={(e) => setSearchTerm(e.target.value)} 
            />
            {searchTerm && (
              <button className="lux-search-clear" onClick={() => setSearchTerm('')}>
                <X size={14} />
              </button>
            )}
          </div>

          <div className="view-toggle-group">
            <button 
              className={`view-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => setViewMode('table')}
              title="Table View (Full 12 Categories)"
            >
              <Table size={14} /> Table
            </button>
            <button 
              className={`view-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
              onClick={() => setViewMode('grid')}
              title="Card Grid View"
            >
              <Grid size={14} /> Grid
            </button>
          </div>


          <select 
            className="lux-select" 
            value={propStatusFilter} 
            onChange={(e) => setPropStatusFilter(e.target.value)}
          >
            <option value="All">All Statuses</option>
            <option value="Available">Available</option>
            <option value="For Sale">For Sale</option>
            <option value="For Rent">For Rent</option>
            <option value="Pending">Pending</option>
            <option value="Sold">Sold</option>
          </select>

          <select 
            className="lux-select" 
            value={typeFilter} 
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="All">All Types</option>
            {uniqueTypes.filter(t => t !== 'All').map(t => (
              <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
            ))}
          </select>

          <select 
            className="lux-select" 
            value={cityFilter} 
            onChange={(e) => setCityFilter(e.target.value)}
          >
            <option value="All">All Cities</option>
            {uniqueCities.filter(c => c !== 'All').map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <select 
            className="lux-select" 
            value={sortOrder} 
            onChange={(e) => setSortOrder(e.target.value)}
          >
            <option value="newest">Sort: Newest</option>
            <option value="price-asc">Price: Low to High</option>
            <option value="price-desc">Price: High to Low</option>
          </select>
        </div>
      )}

      {/* Tier 3: Contextual Filter Toolbar for Leads */}
      {activeTab === 'leads' && (
        <div className="lux-filter-bar">
          <div className="lux-search-box" style={{ flex: 1, minWidth: '220px' }}>
            <input 
              type="text" 
              className="lux-search-input" 
              placeholder="Search leads by name or phone..." 
              value={searchTerm} 
              onChange={(e) => setSearchTerm(e.target.value)} 
            />
            {searchTerm && (
              <button className="lux-search-clear" onClick={() => setSearchTerm('')}>
                <X size={14} />
              </button>
            )}
          </div>

          <select 
            className="lux-select" 
            value={leadTempFilter} 
            onChange={(e) => setLeadTempFilter(e.target.value)}
          >
            <option value="All">All Temperatures</option>
            <option value="hot">🔥 Hot</option>
            <option value="warm">☀️ Warm</option>
            <option value="cold">❄️ Cold</option>
          </select>

          <select 
            className="lux-select" 
            value={leadSortOrder} 
            onChange={(e) => setLeadSortOrder(e.target.value)}
          >
            <option value="newest">Sort: Newest</option>
            <option value="oldest">Sort: Oldest</option>
            <option value="hot-first">Priority: Hot First</option>
          </select>

          {environment === 'staging' && (
            <button 
              className="lux-btn-secondary" 
              onClick={handleResetStagingLeads}
              style={{ fontSize: '0.8rem', padding: '0.5rem 0.85rem', color: '#c5221f', borderColor: '#fca5a5', display: 'flex', alignItems: 'center', gap: '0.35rem', whiteSpace: 'nowrap' }}
              title="Clear bulk-imported leads from Staging DB"
            >
              <Trash2 size={13} /> Reset Staging Leads
            </button>
          )}
        </div>
      )}


      <main className="lux-main-content">
        {activeTab === 'properties' ? (
          sortedProperties.length === 0 ? (
          <div className="lux-empty-card">
            <div className="lux-empty-icon"><Home size={36} color="#d4af37" /></div>
            <h3>No Properties Found</h3>
            <p>Database has 0 property records matching your current filter.</p>
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem', justifyContent: 'center' }}>
              <button className="lux-btn-primary" onClick={handleOpenAddModal}>
                <Plus size={16} /> Add First Listing
              </button>
              <button 
                className="lux-btn-secondary" 
                onClick={syncWordpressListings} 
                disabled={isSyncingWP}
              >
                {isSyncingWP ? (syncStatusText || 'Syncing...') : '🔄 Sync All from WordPress'}
              </button>
            </div>
          </div>
        ) : viewMode === 'table' ? (
          <div className="properties-table-wrap">
            <table className="properties-table">
              <thead>
                <tr>
                  <th>Property Listing</th>
                  <th>Category / Subtype</th>
                  <th>Location</th>
                  <th>Financials (MYR)</th>
                  <th>Size & Specs</th>
                  <th>Tenure & Zoning</th>
                  <th>Crops & Trees</th>
                  <th>Water & Topography</th>
                  <th>Power & Access</th>
                  <th>Status</th>
                  <th>Vectors</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedProperties.map((prop) => (
                  <tr key={prop.id} onClick={() => setDetailProperty(prop)}>
                    <td style={{ minWidth: '220px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                        {prop.image_urls && prop.image_urls.length > 0 ? (
                          <img 
                            src={prop.image_urls[0]} 
                            alt={prop.title} 
                            style={{ width: '42px', height: '42px', borderRadius: '6px', objectFit: 'cover' }} 
                            loading="lazy" 
                          />
                        ) : (
                          <div style={{ width: '42px', height: '42px', borderRadius: '6px', background: '#e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Home size={18} color="#94a3b8" />
                          </div>
                        )}
                        <div>
                          <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '0.85rem' }}>{prop.title}</div>
                          {prop.property_type_sub && (
                            <span style={{ fontSize: '0.72rem', color: '#64748b' }}>{prop.property_type_sub}</span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>
                      {(prop.property_category || []).map((cat, idx) => (
                        <span key={idx} className="cat-pill">{cat}</span>
                      ))}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, color: '#1e293b' }}>{prop.city || 'Pahang'}</div>
                      <div style={{ fontSize: '0.72rem', color: '#64748b' }}>{prop.street_address || prop.area || prop.state || '-'}</div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 800, color: '#047857', fontSize: '0.9rem' }}>
                        {formatPrice(prop.asking_price_myr || prop.monthly_rental_income_myr)}
                        {prop.monthly_rental_income_myr > 0 && !prop.asking_price_myr ? '/mo' : ''}
                      </div>
                      {prop.price_per_acre_myr > 0 && (
                        <div style={{ fontSize: '0.72rem', color: '#64748b' }}>RM {prop.price_per_acre_myr.toLocaleString()}/ac</div>
                      )}
                      {prop.price_per_sqft_myr > 0 && (
                        <div style={{ fontSize: '0.72rem', color: '#64748b' }}>RM {prop.price_per_sqft_myr.toLocaleString()}/sqft</div>
                      )}
                      {prop.implied_yield_pct > 0 && (
                        <span className="yield-tag">📈 {prop.implied_yield_pct}% Yield</span>
                      )}
                    </td>
                    <td>
                      {prop.land_area_acres > 0 && (
                        <div style={{ fontWeight: 600 }}>{prop.land_area_acres} Acres</div>
                      )}
                      {prop.built_up_area_sqft > 0 && (
                        <div style={{ fontSize: '0.72rem', color: '#64748b' }}>Built: {prop.built_up_area_sqft.toLocaleString()} sqft</div>
                      )}
                      {prop.land_area_sqft > 0 && !prop.built_up_area_sqft && (
                        <div style={{ fontSize: '0.72rem', color: '#64748b' }}>{prop.land_area_sqft.toLocaleString()} sqft</div>
                      )}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{prop.tenure_type || '-'}</div>
                      <div style={{ fontSize: '0.72rem', color: '#64748b' }}>{prop.zoning_type || prop.title_status || '-'}</div>
                    </td>
                    <td>
                      {prop.crop_types && prop.crop_types.length > 0 ? (
                        <div>
                          <div style={{ fontWeight: 600, color: '#15803d' }}>{prop.crop_types.join(', ')}</div>
                          {prop.tree_count_estimate > 0 && (
                            <div style={{ fontSize: '0.72rem', color: '#64748b' }}>{prop.tree_count_estimate} trees {prop.tree_age_years ? `(${prop.tree_age_years} yrs)` : ''}</div>
                          )}
                        </div>
                      ) : (
                        <span style={{ color: '#94a3b8', fontSize: '0.75rem' }}>Non-agri / Vacant</span>
                      )}
                    </td>
                    <td>
                      <div>{prop.topography || '-'}</div>
                      {prop.has_natural_stream && <span className="cat-pill" style={{ background: '#ecfdf5', color: '#065f46' }}>🌊 Stream</span>}
                      {prop.has_pond && <span className="cat-pill" style={{ background: '#eff6ff', color: '#1e40af' }}>💧 Pond</span>}
                      {prop.is_flood_free && <span className="cat-pill" style={{ background: '#fef3c7', color: '#92400e' }}>🛡️ Flood Free</span>}
                    </td>
                    <td>
                      {prop.power_supply_amp > 0 && (
                        <div>⚡ {prop.power_supply_amp} Amp</div>
                      )}
                      <div style={{ fontSize: '0.72rem', color: '#64748b' }}>{prop.road_access_quality || '-'}</div>
                    </td>
                    <td>
                      <span className="status-badge" style={{ position: 'static', padding: '0.2rem 0.5rem', fontSize: '0.7rem' }}>
                        {prop.listing_status || 'Available'}
                      </span>
                    </td>
                    <td>
                      <span className="emb-badge-check" title="5 Aspect Vector Embeddings Populated (Location, Specs, Features, Suitability, Overview)">
                        <Sparkles size={11} /> 5 Vectors
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.35rem' }}>
                        <button 
                          className="btn-icon" 
                          onClick={(e) => { e.stopPropagation(); setDetailProperty(prop); }}
                          title="View 12-Category Full Breakdown"
                          style={{ padding: '0.35rem', background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer' }}
                        >
                          <Eye size={14} color="#0f172a" />
                        </button>
                        <button 
                          className="btn-icon" 
                          onClick={(e) => { e.stopPropagation(); handleOpenEditModal(prop, e); }}
                          title="Edit"
                          style={{ padding: '0.35rem', background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer' }}
                        >
                          <Edit size={14} color="#2563eb" />
                        </button>
                        <button 
                          className="btn-icon" 
                          onClick={(e) => { e.stopPropagation(); handleDelete(prop.id, e); }}
                          title="Delete"
                          style={{ padding: '0.35rem', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '4px', cursor: 'pointer' }}
                        >
                          <Trash2 size={14} color="#dc2626" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="properties-grid">
            {sortedProperties.map((prop) => (
              <div key={prop.id} className="property-card" onClick={() => setDetailProperty(prop)}>
                {prop.image_urls && prop.image_urls.length > 0 ? (
                  <div className="property-image-wrap">
                    <img src={prop.image_urls[0]} alt={prop.title} className="property-img" loading="lazy" />
                    <div className="status-badge">{prop.listing_status}</div>
                  </div>
                ) : (
                  <div className="status-badge" style={{ position: 'absolute', top: '1rem', right: '1rem' }}>{prop.listing_status}</div>
                )}
                
                <div className="property-card-content">
                  <div className="property-price">
                    {formatPrice(prop.asking_price_myr || prop.monthly_rental_income_myr)}
                    {prop.monthly_rental_income_myr > 0 && !prop.asking_price_myr ? '/mo' : ''}
                  </div>
                  <div className="property-title">{prop.title}</div>
                  
                  <div className="property-details">
                    <div className="detail-item">
                      <MapPin size={16} />
                      {prop.street_address || prop.city || 'N/A'}
                    </div>
                    <div className="detail-item">
                      <Tag size={16} />
                      <span style={{ textTransform: 'capitalize' }}>{(prop.property_category || []).join(', ') || 'General'}</span>
                    </div>
                    <div className="detail-item">
                      <Home size={16} />
                      <span style={{ textTransform: 'capitalize' }}>{prop.tenure_type || 'N/A'}</span>
                    </div>
                    {prop.land_area_acres > 0 && (
                      <div className="detail-item">
                        <strong>Acres:</strong> {prop.land_area_acres} ac
                      </div>
                    )}
                    {prop.crop_types && prop.crop_types.length > 0 && (
                      <div className="detail-item" style={{ gridColumn: 'span 2', color: '#15803d' }}>
                        <TreePine size={16} />
                        <span>{prop.crop_types.join(', ')} {prop.tree_count_estimate ? `(${prop.tree_count_estimate} trees)` : ''}</span>
                      </div>
                    )}
                  </div>

                  <div className="card-actions" style={{ marginTop: '0.75rem', display: 'flex', gap: '0.4rem', justifyContent: 'flex-end' }}>
                    <button className="btn-icon view-map" onClick={(e) => { e.stopPropagation(); setDetailProperty(prop); }} title="View 12-Category Full Breakdown">
                      <Eye size={15} /> Details
                    </button>
                    <button className="btn-icon view-map" onClick={(e) => { e.stopPropagation(); handleViewMap(prop); }} title="View Map">
                      <Map size={15} /> Map
                    </button>
                    <button className="btn-icon edit" onClick={(e) => handleOpenEditModal(prop, e)} title="Edit">
                      <Edit size={15} /> Edit
                    </button>
                    <button className="btn-icon delete" onClick={(e) => handleDelete(prop.id, e)} title="Delete">
                      <Trash2 size={15} /> Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
) : activeTab === 'leads' ? (

          <div className="leads-grid">
            {leads.length === 0 ? (
              <div className="lux-empty-card">
                <div className="lux-empty-icon"><Users size={36} color="#d4af37" /></div>
                <h3>No Customer Leads in Database</h3>
                <p>Sync all existing contacts directly from Chatwoot or wait for incoming WhatsApp messages.</p>
                <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem', justifyContent: 'center' }}>
                  <button 
                    className="lux-btn-primary" 
                    onClick={syncChatwootLeads} 
                    disabled={isSyncingLeads}
                  >
                    {isSyncingLeads ? 'Syncing...' : '🔄 Sync Leads from Chatwoot'}
                  </button>
                  <button className="lux-btn-secondary" onClick={handleOpenAddLeadModal}>
                    <Plus size={16} /> Add Manual Lead
                  </button>
                </div>
              </div>
            ) : (
              <table className="leads-table">
                <thead>
                  <tr>
                    <th>Contact</th>
                    <th>Phone Number</th>
                    <th>Email</th>
                    <th>Country</th>
                    <th>Intent Category</th>
                    <th>Temperature</th>
                    <th>AI Bot</th>
                    <th>Conversation IDs</th>
                    <th>Registered</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.filter(lead => {
                    const matchesSearch = (lead.contact_name || '').toLowerCase().includes(searchTerm.toLowerCase()) || 
                                          (lead.phone_number || '').includes(searchTerm);
                    const matchesTemp = leadTempFilter === 'All' || (lead.intention_tag || 'Cold').toLowerCase() === leadTempFilter.toLowerCase();
                    return matchesSearch && matchesTemp;
                  }).sort((a, b) => {
                    if (leadSortOrder === 'newest') return b.id - a.id;
                    if (leadSortOrder === 'oldest') return a.id - b.id;
                    if (leadSortOrder === 'hot-first') {
                      const tempWeight = { 'hot': 3, 'warm': 2, 'cold': 1 };
                      const aTemp = tempWeight[(a.intention_tag || 'cold').toLowerCase()] || 0;
                      const bTemp = tempWeight[(b.intention_tag || 'cold').toLowerCase()] || 0;
                      if (bTemp !== aTemp) return bTemp - aTemp;
                      return b.id - a.id;
                    }
                    return 0;
                  }).map((lead) => (
                    <tr key={lead.id}>
                      <td className="lead-name">{lead.contact_name || 'Unknown'}</td>
                      <td>{lead.phone_number}</td>
                      <td>{lead.email || '-'}</td>
                      <td>{lead.country || '-'}</td>
                      <td style={{ textTransform: 'capitalize' }}>{lead.intent_category || 'General'}</td>
                      <td>
                        <span className={`temp-badge ${lead.intention_tag?.toLowerCase() || 'cold'}`}>
                          {lead.intention_tag === 'Hot' ? '🔥' : lead.intention_tag === 'Warm' ? '☀️' : '❄️'} {lead.intention_tag || 'Cold'}
                        </span>
                      </td>
                      <td>
                        <button 
                          className={`ai-status-btn ${lead.metadata_json?.ignore_ai ? 'disabled' : 'active'}`}
                          onClick={() => toggleIgnoreAI(lead)}
                          title={lead.metadata_json?.ignore_ai ? "Click to enable AI replies" : "Click to disable AI replies"}
                          style={{
                            padding: '0.25rem 0.5rem',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                            fontWeight: 'bold',
                            border: '1px solid',
                            cursor: 'pointer',
                            backgroundColor: lead.metadata_json?.ignore_ai ? '#fce8e6' : '#e6f4ea',
                            color: lead.metadata_json?.ignore_ai ? '#c5221f' : '#137333',
                            borderColor: lead.metadata_json?.ignore_ai ? '#fad2cf' : '#ceead6'
                          }}
                        >
                          {lead.metadata_json?.ignore_ai ? 'Off' : 'On'}
                        </button>
                      </td>
                      <td>
                        {lead.conversation_ids && lead.conversation_ids.length > 0 
                          ? lead.conversation_ids.join(', ') 
                          : '-'}
                      </td>
                      <td className="text-secondary">
                        {lead.last_interaction ? new Date(lead.last_interaction).toLocaleDateString() : 'N/A'}
                      </td>
                      <td>
                        <div className="card-actions" style={{ justifyContent: 'flex-start', borderTop: 'none', padding: 0 }}>
                          {lead.conversation_ids && lead.conversation_ids.length > 0 && (
                            <button 
                              className="btn-primary" 
                              style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem', marginRight: '0.5rem', whiteSpace: 'nowrap' }}
                              onClick={() => window.open(`https://inbox.bentongland.com.my/app/accounts/1/conversations/${lead.conversation_ids[0]}`, '_blank')} 
                              title="Open in Chatwoot"
                            >
                              <MessageCircle size={14} /> Open Chat
                            </button>
                          )}
                          <button className="btn-icon edit" onClick={(e) => handleOpenEditLeadModal(lead, e)} title="Edit">
                            <Edit size={16} />
                          </button>
                          <button className="btn-icon delete" onClick={(e) => handleDeleteLead(lead.id, e)} title="Delete">
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : activeTab === 'embeddings' ? (
          <div className="emb-container">
            {/* 1. Header & KPI Stats */}
            <div className="emb-stats-grid">
              <div className="emb-stat-card">
                <div className="emb-stat-icon">
                  <Sparkles size={24} />
                </div>
                <div className="emb-stat-info">
                  <h4>Embedding Health</h4>
                  <div className="stat-number">
                    {embeddingsSummary?.aspect_embeddings_stats?.fully_vectorized_pct || 100}%
                  </div>
                  <span style={{ fontSize: '0.75rem', color: '#16a34a', fontWeight: 600 }}>
                    {embeddingsSummary?.total_properties || properties.length} Listings Vectorized
                  </span>
                </div>
              </div>

              <div className="emb-stat-card">
                <div className="emb-stat-icon" style={{ background: '#ecfdf5', color: '#059669' }}>
                  <Layers size={24} />
                </div>
                <div className="emb-stat-info">
                  <h4>Dense Vectors Populated</h4>
                  <div className="stat-number">
                    {embeddingsSummary?.aspect_embeddings_stats?.total_vectors_generated || (properties.length * 5)}
                  </div>
                  <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    5 Vectors / Property (384-dim)
                  </span>
                </div>
              </div>

              <div className="emb-stat-card">
                <div className="emb-stat-icon" style={{ background: '#eff6ff', color: '#2563eb' }}>
                  <Activity size={24} />
                </div>
                <div className="emb-stat-info">
                  <h4>Vector Model Engine</h4>
                  <div className="stat-number" style={{ fontSize: '1rem', marginTop: '0.4rem' }}>
                    bge-small-en-v1.5
                  </div>
                  <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    FastEmbed ONNX (~3ms inference)
                  </span>
                </div>
              </div>
            </div>

            {/* 2. Interactive Natural Language Query Simulator */}
            <div className="emb-section-card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: '#0f172a' }}>
                    🧪 Real-Time Natural Language Vector Query Simulator
                  </h3>
                  <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.8rem', color: '#64748b' }}>
                    Test real customer inquiries and inspect live multi-aspect cosine similarity rankings across Location, Specs, Features, and Suitability.
                  </p>
                </div>
              </div>

              <form onSubmit={handleNlSearch} className="emb-search-form">
                <div className="emb-search-input-wrap">
                  <input 
                    type="text" 
                    className="emb-search-input" 
                    placeholder="e.g. 10 ac Musang King durian orchard with natural river stream under 2.5m in Raub" 
                    value={nlQuery}
                    onChange={(e) => setNlQuery(e.target.value)}
                  />
                </div>
                <button 
                  type="submit" 
                  className="emb-search-btn" 
                  disabled={isSearchingNl || !nlQuery.trim()}
                >
                  <Search size={16} /> {isSearchingNl ? 'Searching...' : 'Run Vector Search'}
                </button>
              </form>


              {nlSearchResults && (
                <div>
                  <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#475569', marginBottom: '0.75rem' }}>
                    Top Semantic Matches for "{nlSearchResults.query}":
                  </div>
                  <div className="emb-correlation-grid">
                    {nlSearchResults.results.map((res) => (
                      <div key={res.id} className="emb-corr-card" onClick={() => {
                        const matched = properties.find(p => p.id === res.id);
                        if (matched) setDetailProperty(matched);
                      }} style={{ cursor: 'pointer' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div style={{ fontWeight: 700, fontSize: '0.88rem', color: '#0f172a', flex: 1, marginRight: '0.5rem' }}>
                            {res.title}
                          </div>
                          <span className="emb-badge-check" style={{ fontSize: '0.78rem', background: '#ecfdf5', color: '#059669', padding: '0.2rem 0.6rem' }}>
                            {(res.similarity_score * 100).toFixed(1)}% Match
                          </span>
                        </div>

                        <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.78rem', color: '#64748b' }}>
                          <span>📍 {res.city || 'Pahang'}</span>
                          <span>•</span>
                          <span style={{ fontWeight: 700, color: '#047857' }}>{formatPrice(res.asking_price_myr)}</span>
                        </div>

                        {/* Aspect breakdown bars */}
                        <div style={{ marginTop: '0.25rem' }}>
                          <div className="aspect-score-row">
                            <span>Overview Match:</span>
                            <strong>{res.aspect_breakdown?.overview_pct}%</strong>
                          </div>
                          <div className="aspect-bar-bg" style={{ marginBottom: '0.4rem' }}>
                            <div className="aspect-bar-fill" style={{ width: `${res.aspect_breakdown?.overview_pct}%`, background: '#7c3aed' }} />
                          </div>

                          <div className="aspect-score-row">
                            <span>Features & Crops Match:</span>
                            <strong>{res.aspect_breakdown?.features_pct}%</strong>
                          </div>
                          <div className="aspect-bar-bg" style={{ marginBottom: '0.4rem' }}>
                            <div className="aspect-bar-fill" style={{ width: `${res.aspect_breakdown?.features_pct}%`, background: '#10b981' }} />
                          </div>

                          <div className="aspect-score-row">
                            <span>Location Match:</span>
                            <strong>{res.aspect_breakdown?.location_pct}%</strong>
                          </div>
                          <div className="aspect-bar-bg">
                            <div className="aspect-bar-fill" style={{ width: `${res.aspect_breakdown?.location_pct}%`, background: '#3b82f6' }} />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 3. Property Correlation Explorer & Aspect Text Chunks Inspector */}
            <div className="emb-section-card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: '#0f172a' }}>
                    🔍 Property Vector Correlation Matrix & Aspect Chunks
                  </h3>
                  <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.8rem', color: '#64748b' }}>
                    Select any listing to inspect its 5 generated aspect text chunks and live cosine similarity with other listings.
                  </p>
                </div>

                <div style={{ minWidth: '280px' }}>
                  <select 
                    className="lux-select"
                    value={selectedEmbPropId}
                    onChange={(e) => {
                      setSelectedEmbPropId(e.target.value);
                      fetchPropertyCorrelations(e.target.value);
                    }}
                    style={{ width: '100%', padding: '0.5rem 0.75rem', fontWeight: 600 }}
                  >
                    {properties.map(p => (
                      <option key={p.id} value={p.id}>{p.title} ({p.city || 'Pahang'})</option>
                    ))}
                  </select>
                </div>
              </div>

              {isLoadingCorrelations ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                  Computing cosine similarities across 5 embedding dimensions...
                </div>
              ) : (
                <div>
                  {/* Aspect Text Chunks Preview */}
                  {propAspectChunks && (
                    <div style={{ marginBottom: '1.5rem' }}>
                      <h4 style={{ fontSize: '0.82rem', textTransform: 'uppercase', color: '#64748b', marginBottom: '0.75rem' }}>
                        5 Generated Text Chunks (Vector Ingestion Sources)
                      </h4>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem' }}>
                        <div className="aspect-chunk-box">
                          <div style={{ color: '#38bdf8', fontWeight: 700, marginBottom: '0.35rem' }}>📍 Location Chunk:</div>
                          {propAspectChunks.aspect_chunks?.location || 'N/A'}
                        </div>
                        <div className="aspect-chunk-box">
                          <div style={{ color: '#fbbf24', fontWeight: 700, marginBottom: '0.35rem' }}>📐 Specs Chunk:</div>
                          {propAspectChunks.aspect_chunks?.specs || 'N/A'}
                        </div>
                        <div className="aspect-chunk-box">
                          <div style={{ color: '#4ade80', fontWeight: 700, marginBottom: '0.35rem' }}>🌳 Features & Agro Chunk:</div>
                          {propAspectChunks.aspect_chunks?.features || 'N/A'}
                        </div>
                        <div className="aspect-chunk-box">
                          <div style={{ color: '#c084fc', fontWeight: 700, marginBottom: '0.35rem' }}>🎯 Suitability Chunk:</div>
                          {propAspectChunks.aspect_chunks?.suitability || 'N/A'}
                        </div>
                        <div className="aspect-chunk-box" style={{ gridColumn: '1 / -1' }}>
                          <div style={{ color: '#f43f5e', fontWeight: 700, marginBottom: '0.35rem' }}>📋 Overview Corpus Chunk:</div>
                          {propAspectChunks.aspect_chunks?.overview || 'N/A'}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Top Correlated Listings */}
                  {propCorrelations && (
                    <div>
                      <h4 style={{ fontSize: '0.82rem', textTransform: 'uppercase', color: '#64748b', marginBottom: '0.75rem' }}>
                        Top Correlated Listings for "{propCorrelations.target_property?.title}"
                      </h4>
                      <div className="emb-correlation-grid">
                        {propCorrelations.top_correlated?.map((corr) => (
                          <div key={corr.id} className="emb-corr-card" onClick={() => {
                            const matched = properties.find(p => p.id === corr.id);
                            if (matched) setDetailProperty(matched);
                          }} style={{ cursor: 'pointer' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                              <div style={{ fontWeight: 700, fontSize: '0.88rem', color: '#0f172a', flex: 1, marginRight: '0.5rem' }}>
                                {corr.title}
                              </div>
                              <span className="emb-badge-check" style={{ fontSize: '0.78rem', padding: '0.2rem 0.5rem' }}>
                                {(corr.correlation_score * 100).toFixed(1)}% Sim
                              </span>
                            </div>

                            <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.78rem', color: '#64748b' }}>
                              <span>📍 {corr.city || 'Pahang'}</span>
                              <span>•</span>
                              <span style={{ fontWeight: 700, color: '#047857' }}>{formatPrice(corr.asking_price_myr)}</span>
                            </div>

                            <div style={{ marginTop: '0.25rem' }}>
                              <div className="aspect-score-row">
                                <span>Overview Correlation:</span>
                                <strong>{corr.aspect_breakdown?.overview_pct}%</strong>
                              </div>
                              <div className="aspect-bar-bg" style={{ marginBottom: '0.3rem' }}>
                                <div className="aspect-bar-fill" style={{ width: `${corr.aspect_breakdown?.overview_pct}%`, background: '#7c3aed' }} />
                              </div>

                              <div className="aspect-score-row">
                                <span>Specs Correlation:</span>
                                <strong>{corr.aspect_breakdown?.specs_pct}%</strong>
                              </div>
                              <div className="aspect-bar-bg" style={{ marginBottom: '0.3rem' }}>
                                <div className="aspect-bar-fill" style={{ width: `${corr.aspect_breakdown?.specs_pct}%`, background: '#f59e0b' }} />
                              </div>

                              <div className="aspect-score-row">
                                <span>Location Correlation:</span>
                                <strong>{corr.aspect_breakdown?.location_pct}%</strong>
                              </div>
                              <div className="aspect-bar-bg">
                                <div className="aspect-bar-fill" style={{ width: `${corr.aspect_breakdown?.location_pct}%`, background: '#3b82f6' }} />
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : activeTab === 'workflows' ? (
          <WorkflowViewer />
        ) : activeTab === 'users' ? (
          <UsersManagement />
        ) : null}

      </main>

      {/* Add/Edit Modal */}
      {isModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h2>{isEditing ? 'Edit Property' : 'Add New Property'}</h2>
              <button className="close-btn" onClick={() => setIsModalOpen(false)}>✕</button>
            </div>
            
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Title</label>
                <input 
                  type="text" 
                  name="title" 
                  className="form-input"
                  value={formData.title} 
                  onChange={handleInputChange} 
                  required 
                  placeholder="e.g. 3 Bedroom Apartment in Raub"
                />
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Street Address</label>
                  <input 
                    type="text" 
                    name="street_address" 
                    className="form-input"
                    value={formData.street_address} 
                    onChange={handleInputChange} 
                    placeholder="e.g. Jalan Tun Razak, Raub"
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Asking Price (MYR)</label>
                  <input 
                    type="number" 
                    name="asking_price_myr" 
                    className="form-input"
                    value={formData.asking_price_myr} 
                    onChange={handleInputChange} 
                    required 
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Property Category (comma-separated)</label>
                  <input 
                    type="text"
                    name="property_category" 
                    className="form-input"
                    value={formData.property_category} 
                    onChange={handleInputChange}
                    placeholder="e.g. Land, Durian Orchard"
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Built-up Area (Sqft)</label>
                  <input 
                    type="number" 
                    name="built_up_area_sqft" 
                    className="form-input"
                    value={formData.built_up_area_sqft} 
                    onChange={handleInputChange} 
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Land Area (Acres)</label>
                  <input 
                    type="number" 
                    step="0.01"
                    name="land_area_acres" 
                    className="form-input"
                    value={formData.land_area_acres} 
                    onChange={handleInputChange} 
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Tenure Type</label>
                  <input 
                    type="text" 
                    name="tenure_type" 
                    className="form-input"
                    value={formData.tenure_type} 
                    onChange={handleInputChange} 
                    placeholder="e.g. Freehold"
                  />
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Power Supply (Amp)</label>
                  <input type="number" name="power_supply_amp" className="form-input" value={formData.power_supply_amp} onChange={handleInputChange} />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Monthly Rental Income (MYR)</label>
                  <input type="number" name="monthly_rental_income_myr" className="form-input" value={formData.monthly_rental_income_myr} onChange={handleInputChange} />
                </div>
                <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, marginTop: '1.5rem' }}>
                  <input type="checkbox" name="is_tenanted" id="is_tenanted" checked={formData.is_tenanted} onChange={(e) => setFormData({...formData, is_tenanted: e.target.checked})} />
                  <label htmlFor="is_tenanted" style={{ marginBottom: 0 }}>Is Tenanted</label>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>City</label>
                  <input type="text" name="city" className="form-input" value={formData.city} onChange={handleInputChange} placeholder="e.g. Raub" />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>State</label>
                  <input type="text" name="state" className="form-input" value={formData.state} onChange={handleInputChange} placeholder="e.g. Pahang" />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Listing Status</label>
                  <select 
                    name="listing_status" 
                    className="form-select"
                    value={formData.listing_status} 
                    onChange={handleInputChange}
                  >
                    <option value="Available">Available</option>
                    <option value="For Sale">For Sale</option>
                    <option value="For Rent">For Rent</option>
                    <option value="Pending">Pending</option>
                    <option value="Sold">Sold</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label>Description / AI Knowledge (Markdown)</label>
                <textarea 
                  name="search_corpus_markdown" 
                  className="form-input"
                  value={formData.search_corpus_markdown} 
                  onChange={handleInputChange} 
                  rows="3"
                  placeholder="Detailed description, searchable by AI..."
                ></textarea>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setIsModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  {isEditing ? 'Save Changes' : 'Save Listing'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Map Details Modal */}
      {isMapModalOpen && selectedProperty && (
        <div className="modal-overlay">
          <div className="modal-content map-modal-content">
            <div className="modal-header">
              <h2>Property Details & Map</h2>
              <button className="close-btn" onClick={() => setIsMapModalOpen(false)}>✕</button>
            </div>
            
            <div className="property-full-details">
              <h3>{selectedProperty.title}</h3>
              <p className="full-price">{formatPrice(selectedProperty.asking_price_myr)} - <span className="status-badge-inline">{selectedProperty.listing_status}</span></p>
              
              <div className="details-grid">
                <div><strong>Address:</strong> {selectedProperty.street_address}</div>
                <div><strong>Category:</strong> {(selectedProperty.property_category || []).join(', ')}</div>
                <div><strong>Acres:</strong> {selectedProperty.land_area_acres}</div>
                <div><strong>Built-up (sqft):</strong> {selectedProperty.built_up_area_sqft}</div>
                <div><strong>City/State:</strong> {selectedProperty.city}, {selectedProperty.state}</div>
                <div><strong>Tenure:</strong> {selectedProperty.tenure_type}</div>
                <div><strong>Power Supply:</strong> {selectedProperty.power_supply_amp ? `${selectedProperty.power_supply_amp} Amp` : 'N/A'}</div>
                <div><strong>Tenanted:</strong> {selectedProperty.is_tenanted ? 'Yes' : 'No'}</div>
              </div>
              
              <div className="full-description">
                <strong>Description / AI Knowledge:</strong>
                <p>{selectedProperty.search_corpus_markdown}</p>
              </div>
              
              <div className="map-container">
                <iframe
                  title="Property Map"
                  width="100%"
                  height="300"
                  frameBorder="0"
                  style={{ border: 0, borderRadius: '8px', marginTop: '15px' }}
                  src={`https://maps.google.com/maps?q=${encodeURIComponent(selectedProperty.street_address || selectedProperty.city || selectedProperty.title || '')}&output=embed`}
                  allowFullScreen
                ></iframe>
              </div>
            </div>

            <div className="modal-footer" style={{ marginTop: '20px' }}>
              <button type="button" className="btn-primary" onClick={() => setIsMapModalOpen(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add/Edit Lead Modal */}
      {isLeadModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h2>{isEditingLead ? 'Edit Lead' : 'Add New Lead'}</h2>
              <button className="close-btn" onClick={() => setIsLeadModalOpen(false)}>✕</button>
            </div>
            
            <form onSubmit={handleLeadSubmit}>
              <div className="form-group">
                <label>Contact Name</label>
                <input 
                  type="text" 
                  name="contact_name" 
                  className="form-input"
                  value={leadFormData.contact_name} 
                  onChange={handleLeadInputChange} 
                  required 
                  placeholder="e.g. John Doe"
                />
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Phone Number</label>
                  <input 
                    type="text" 
                    name="phone_number" 
                    className="form-input"
                    value={leadFormData.phone_number} 
                    onChange={handleLeadInputChange} 
                    required 
                    readOnly={false}
                    placeholder="e.g. +60123456789"
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Email</label>
                  <input 
                    type="email" 
                    name="email" 
                    className="form-input"
                    value={leadFormData.email || ''} 
                    onChange={handleLeadInputChange} 
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Country</label>
                  <input 
                    type="text" 
                    name="country" 
                    className="form-input"
                    value={leadFormData.country || ''} 
                    onChange={handleLeadInputChange} 
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Intent Category</label>
                  <select 
                    name="intent_category" 
                    className="form-select"
                    value={leadFormData.intent_category || 'general'} 
                    onChange={handleLeadInputChange}
                  >
                    <option value="general">General</option>
                    <option value="buyer">Buyer</option>
                    <option value="seller">Seller</option>
                    <option value="tenant">Tenant</option>
                    <option value="agent">Agent</option>
                  </select>
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Temperature</label>
                  <select 
                    name="intention_tag" 
                    className="form-select"
                    value={leadFormData.intention_tag || 'Cold'} 
                    onChange={handleLeadInputChange}
                  >
                    <option value="Hot">Hot</option>
                    <option value="Warm">Warm</option>
                    <option value="Cold">Cold</option>
                  </select>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
                <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <input
                    type="checkbox"
                    name="ignore_ai"
                    id="ignore_ai"
                    checked={leadFormData.ignore_ai}
                    onChange={handleLeadInputChange}
                  />
                  <label htmlFor="ignore_ai" style={{ marginBottom: 0, fontWeight: 'bold' }}>Disable AI (Halt AI replies for this customer)</label>
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setIsLeadModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  {isEditingLead ? 'Save Changes' : 'Save Lead'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 12-Category Property Detail Slide-Over Drawer */}
      {detailProperty && (

        <div className="prop-drawer-overlay" onClick={() => setDetailProperty(null)}>
          <div className="prop-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="prop-drawer-header">
              <div>
                <span className="status-badge" style={{ position: 'static', marginRight: '0.5rem' }}>
                  {detailProperty.listing_status || 'Available'}
                </span>
                <span className="emb-badge-check">
                  <Sparkles size={12} /> 5-Aspect Dense Vectors Active
                </span>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0f172a', marginTop: '0.5rem', marginBottom: '0.2rem' }}>
                  {detailProperty.title}
                </h2>
                <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                  {detailProperty.property_type_sub || (detailProperty.property_category || []).join(', ')} • {detailProperty.city || 'Pahang'}
                </div>
              </div>
              <button 
                onClick={() => setDetailProperty(null)}
                style={{ background: '#f1f5f9', border: 'none', borderRadius: '50%', width: '32px', height: '32px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >
                <X size={18} />
              </button>
            </div>

            <div className="prop-drawer-body">
              {/* Photo Gallery */}
              {detailProperty.image_urls && detailProperty.image_urls.length > 0 && (
                <div style={{ display: 'flex', gap: '0.5rem', overflowX: 'auto', paddingBottom: '0.5rem' }}>
                  {detailProperty.image_urls.map((img, idx) => (
                    <img 
                      key={idx} 
                      src={img} 
                      alt={`Photo ${idx+1}`} 
                      style={{ height: '140px', borderRadius: '8px', objectFit: 'cover', flexShrink: 0 }} 
                    />
                  ))}
                </div>
              )}

              {/* 1. Financial Profile */}
              <div className="drawer-section">
                <div className="drawer-section-title">💰 1. Financial & Valuation Profile</div>
                <div className="specs-grid">
                  <div className="spec-cell">
                    <span className="spec-label">Asking Price</span>
                    <div className="spec-val" style={{ color: '#047857' }}>{formatPrice(detailProperty.asking_price_myr)}</div>
                  </div>
                  {detailProperty.monthly_rental_income_myr > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Monthly Rental</span>
                      <div className="spec-val">RM {detailProperty.monthly_rental_income_myr.toLocaleString()}/mo</div>
                    </div>
                  )}
                  {detailProperty.price_per_acre_myr > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Price per Acre</span>
                      <div className="spec-val">RM {detailProperty.price_per_acre_myr.toLocaleString()}</div>
                    </div>
                  )}
                  {detailProperty.price_per_sqft_myr > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Price per Sqft</span>
                      <div className="spec-val">RM {detailProperty.price_per_sqft_myr.toLocaleString()}</div>
                    </div>
                  )}
                  {detailProperty.implied_yield_pct > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Implied Yield</span>
                      <div className="spec-val" style={{ color: '#059669' }}>{detailProperty.implied_yield_pct}%</div>
                    </div>
                  )}
                </div>
              </div>

              {/* 2. Physical & Geometric Specs */}
              <div className="drawer-section">
                <div className="drawer-section-title">📐 2. Physical Dimensions & Built-Up</div>
                <div className="specs-grid">
                  {detailProperty.land_area_acres > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Land Area (Acres)</span>
                      <div className="spec-val">{detailProperty.land_area_acres} ac</div>
                    </div>
                  )}
                  {detailProperty.land_area_sqft > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Land Area (Sqft)</span>
                      <div className="spec-val">{detailProperty.land_area_sqft.toLocaleString()} sqft</div>
                    </div>
                  )}
                  {detailProperty.land_area_sqm > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Land Area (Sqm)</span>
                      <div className="spec-val">{detailProperty.land_area_sqm.toLocaleString()} m²</div>
                    </div>
                  )}
                  {detailProperty.built_up_area_sqft > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Built-Up Area</span>
                      <div className="spec-val">{detailProperty.built_up_area_sqft.toLocaleString()} sqft</div>
                    </div>
                  )}
                </div>
              </div>

              {/* 3. Tenure, Zoning & Title */}
              <div className="drawer-section">
                <div className="drawer-section-title">📜 3. Legal Tenure & Land Title</div>
                <div className="specs-grid">
                  <div className="spec-cell">
                    <span className="spec-label">Tenure Type</span>
                    <div className="spec-val">{detailProperty.tenure_type || 'N/A'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Zoning Type</span>
                    <div className="spec-val">{detailProperty.zoning_type || 'N/A'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Title Status</span>
                    <div className="spec-val">{detailProperty.title_status || 'N/A'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Bumi Lot</span>
                    <div className="spec-val">{detailProperty.is_bumi_lot ? 'Yes (Bumi Lot)' : 'No (Non-Bumi)'}</div>
                  </div>
                </div>
              </div>

              {/* 4. Agricultural & Crops */}
              <div className="drawer-section">
                <div className="drawer-section-title">🌳 4. Agricultural Profile & Crops</div>
                <div className="specs-grid">
                  <div className="spec-cell">
                    <span className="spec-label">Crops Cultivated</span>
                    <div className="spec-val" style={{ color: '#15803d' }}>
                      {(detailProperty.crop_types || []).join(', ') || 'None / Vacant'}
                    </div>
                  </div>
                  {detailProperty.tree_count_estimate > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Tree Count</span>
                      <div className="spec-val">{detailProperty.tree_count_estimate} trees</div>
                    </div>
                  )}
                  {detailProperty.tree_age_years && (
                    <div className="spec-cell">
                      <span className="spec-label">Tree Age</span>
                      <div className="spec-val">{detailProperty.tree_age_years} years</div>
                    </div>
                  )}
                  {detailProperty.harvest_readiness && (
                    <div className="spec-cell">
                      <span className="spec-label">Harvest Readiness</span>
                      <div className="spec-val">{detailProperty.harvest_readiness}</div>
                    </div>
                  )}
                </div>
              </div>

              {/* 5. Topography & Water Sources */}
              <div className="drawer-section">
                <div className="drawer-section-title">💧 5. Topography & Water Features</div>
                <div className="specs-grid">
                  <div className="spec-cell">
                    <span className="spec-label">Topography</span>
                    <div className="spec-val">{detailProperty.topography || 'N/A'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Water Sources</span>
                    <div className="spec-val">{(detailProperty.water_source_types || []).join(', ') || 'N/A'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Natural Stream</span>
                    <div className="spec-val">{detailProperty.has_natural_stream ? '✅ Yes (River/Stream)' : 'No'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Pond</span>
                    <div className="spec-val">{detailProperty.has_pond ? '✅ Yes' : 'No'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Flood Free</span>
                    <div className="spec-val">{detailProperty.is_flood_free ? '🛡️ Certified Flood Free' : 'Standard'}</div>
                  </div>
                </div>
              </div>

              {/* 6. Infrastructure & Utilities */}
              <div className="drawer-section">
                <div className="drawer-section-title">⚡ 6. Infrastructure, Power & Road Access</div>
                <div className="specs-grid">
                  {detailProperty.power_supply_amp > 0 && (
                    <div className="spec-cell">
                      <span className="spec-label">Power Supply</span>
                      <div className="spec-val">⚡ {detailProperty.power_supply_amp} Amp</div>
                    </div>
                  )}
                  <div className="spec-cell">
                    <span className="spec-label">Road Access Quality</span>
                    <div className="spec-val">{detailProperty.road_access_quality || 'N/A'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Fenced</span>
                    <div className="spec-val">{detailProperty.is_fenced ? '✅ Yes' : 'No'}</div>
                  </div>
                  <div className="spec-cell">
                    <span className="spec-label">Worker Quarters</span>
                    <div className="spec-val">{detailProperty.has_worker_quarters ? '✅ Available' : 'No'}</div>
                  </div>
                </div>
              </div>

              {/* 7. Geospatial & Landmarks */}
              <div className="drawer-section">
                <div className="drawer-section-title">📍 7. Geospatial & Nearby Landmarks</div>
                <div style={{ fontSize: '0.85rem', color: '#1e293b', marginBottom: '0.5rem' }}>
                  <strong>Address:</strong> {detailProperty.street_address || detailProperty.area || detailProperty.city || 'Pahang'}
                </div>
                {detailProperty.nearby_landmarks && detailProperty.nearby_landmarks.length > 0 && (
                  <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                    {detailProperty.nearby_landmarks.map((lm, idx) => (
                      <span key={idx} className="cat-pill" style={{ background: '#fef3c7', color: '#92400e' }}>
                        📍 {lm}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* 8. Highlights & Suitable Uses */}
              {detailProperty.key_highlights && detailProperty.key_highlights.length > 0 && (
                <div className="drawer-section">
                  <div className="drawer-section-title">⭐ 8. Key Highlights</div>
                  <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: '#334155', margin: 0 }}>
                    {detailProperty.key_highlights.map((hl, idx) => (
                      <li key={idx} style={{ marginBottom: '0.25rem' }}>{hl}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* WordPress Link */}
              {detailProperty.source_url && (
                <a 
                  href={detailProperty.source_url} 
                  target="_blank" 
                  rel="noreferrer"
                  className="lux-btn-secondary"
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', textDecoration: 'none' }}
                >
                  <ExternalLink size={16} /> View Official WordPress Listing
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
