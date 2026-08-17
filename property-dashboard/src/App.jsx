import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { 
  Plus, Home, MapPin, Tag, Edit, Trash2, Map, Users, 
  LayoutGrid, MessageCircle, X, GitBranch, LogOut, ShieldCheck, Shield, User 
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
  const [isSyncingLeads, setIsSyncingLeads] = useState(false);
  const [isSeedingProps, setIsSeedingProps] = useState(false);

  const fetchProperties = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/properties`);
      setProperties(response.data);
    } catch (error) {
      console.error('Failed to fetch properties:', error);
    }
  };

  const [isSyncingWP, setIsSyncingWP] = useState(false);

  const syncWordpressListings = async () => {
    setIsSyncingWP(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/properties/sync-wordpress`);
      await fetchProperties();
      alert(`WordPress Sync Completed: ${response.data.new_added || 0} new listings added, ${response.data.updated || 0} updated (Total: ${response.data.total_properties || 0})`);
    } catch (error) {
      console.error('Failed to sync WordPress properties:', error);
      alert('Failed to sync properties from WordPress. Please check backend connection.');
    } finally {
      setIsSyncingWP(false);
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
      const response = await axios.get(`${API_BASE_URL}/settings/ai-status`);
      setMasterAiEnabled(response.data.enabled);
    } catch (error) {
      console.error('Failed to fetch master AI status:', error);
    }
  };

  const toggleMasterAi = async () => {
    try {
      const newStatus = !masterAiEnabled;
      const response = await axios.post(`${API_BASE_URL}/settings/ai-status`, { enabled: newStatus });
      setMasterAiEnabled(response.data.enabled);
    } catch (error) {
      console.error('Failed to toggle master AI status:', error);
      alert('Failed to toggle master AI status.');
    }
  };

  const fetchLeads = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/customers`);
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


  // Fetch data on tab change + auto-refresh every 30s for real-time updates
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
  }, [activeTab]);
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
            <div className="lux-brand-title">ERA Realtor • BentongLand DB</div>
            <div className="lux-brand-sub">Real Estate CRM, AI State Engine & RBAC Access</div>
          </div>
        </div>

        <div className="lux-header-actions-group">
          {/* Master AI Toggle Pill */}
          <button 
            className={`lux-ai-toggle-pill ${masterAiEnabled ? 'active' : 'disabled'}`}
            onClick={toggleMasterAi}
            title={masterAiEnabled ? "Click to disable all AI automated responses" : "Click to enable all AI automated responses"}
          >
            <span className={`lux-status-dot ${masterAiEnabled ? 'active' : 'disabled'}`}></span>
            Master AI: <strong>{masterAiEnabled ? 'ON' : 'OFF'}</strong>
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
                {isSyncingWP ? 'Syncing WP...' : '🔄 Sync WordPress'}
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
                {isSyncingWP ? 'Syncing...' : '🔄 Sync All from WordPress'}
              </button>
            </div>
          </div>
        ) : (
          <div className="properties-grid">
            {sortedProperties.map((prop) => (
              <div key={prop.id} className="property-card" onClick={() => handleViewMap(prop)}>
                {prop.image_urls && prop.image_urls.length > 0 ? (
                  <div className="property-image-wrap">
                    <img src={prop.image_urls[0]} alt={prop.title} className="property-img" loading="lazy" />
                    <div className="status-badge">{prop.listing_status}</div>
                  </div>
                ) : (
                  <div className="status-badge" style={{ position: 'absolute', top: '1rem', right: '1rem' }}>{prop.listing_status}</div>
                )}
                
                <div className="property-card-content">
                  <div className="property-price">{formatPrice(prop.asking_price_myr)}</div>
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
                  </div>

                  <div className="card-actions">
                    <button className="btn-icon view-map" onClick={(e) => { e.stopPropagation(); handleViewMap(prop); }} title="View Map & Details">
                      <Map size={16} /> Map
                    </button>
                    <button className="btn-icon edit" onClick={(e) => handleOpenEditModal(prop, e)} title="Edit">
                      <Edit size={16} /> Edit
                    </button>
                    <button className="btn-icon delete" onClick={(e) => handleDelete(prop.id, e)} title="Delete">
                      <Trash2 size={16} /> Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )) : activeTab === 'leads' ? (

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
    </div>
  );
}

export default App;
