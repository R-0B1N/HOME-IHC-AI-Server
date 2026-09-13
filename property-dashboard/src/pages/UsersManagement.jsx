import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { 
  Users, UserPlus, Shield, ShieldCheck, ShieldAlert, 
  Trash2, Edit, Check, X, Search, Lock, RefreshCw, AlertTriangle,
  Phone, Briefcase, MapPin, Building2, Clock, UserCheck, UserX
} from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const ALL_LOCATIONS = [
  'Bentong', 'Temerloh', 'Karak', 'Raub', 'Kuantan', 'Mentakab', 'Pahang', 'Selangor', 'KL'
];

const ALL_PROPERTY_TYPES = [
  'Rental', 'Residential', 'Commercial', 'Land / Agriculture', 'Industrial', 'Durian Land', 'Factory'
];

function UsersManagement({ onUserApproved }) {
  const { user: currentUser, isAdmin } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState('All');

  // Modals
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);

  // Form states
  const [newUserForm, setNewUserForm] = useState({
    username: '',
    email: '',
    phone_number: '',
    password: '',
    fullName: '',
    role: 'agent',
    assigned_locations: [],
    assigned_property_types: [],
    isActive: true,
  });

  const [editUserForm, setEditUserForm] = useState({
    fullName: '',
    email: '',
    phone_number: '',
    role: 'agent',
    assigned_locations: [],
    assigned_property_types: [],
    isActive: true,
    newPassword: '',
  });

  useEffect(() => {
    if (isAdmin) {
      fetchUsers();
    }
  }, [isAdmin]);

  const fetchUsers = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.get(`${API_BASE_URL}/users`);
      setUsers(response.data);
    } catch (err) {
      console.error('Failed to fetch users:', err);
      setError(err.response?.data?.detail || 'Failed to load user accounts.');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await axios.post(`${API_BASE_URL}/users`, {
        username: newUserForm.username.trim(),
        email: newUserForm.email.trim(),
        phone_number: newUserForm.phone_number?.trim() || null,
        password: newUserForm.password,
        full_name: newUserForm.fullName.trim(),
        role: newUserForm.role,
        assigned_locations: newUserForm.assigned_locations,
        assigned_property_types: newUserForm.assigned_property_types,
        is_active: newUserForm.isActive,
      });

      setSuccessMsg(`User ${newUserForm.username} created successfully.`);
      setIsAddModalOpen(false);
      setNewUserForm({
        username: '',
        email: '',
        phone_number: '',
        password: '',
        fullName: '',
        role: 'agent',
        assigned_locations: [],
        assigned_property_types: [],
        isActive: true,
      });
      fetchUsers();
      if (onUserApproved) onUserApproved();
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create user account.');
    }
  };

  const handleOpenEdit = (targetUser) => {
    setSelectedUser(targetUser);
    setEditUserForm({
      fullName: targetUser.full_name || '',
      email: targetUser.email || '',
      phone_number: targetUser.phone_number || '',
      role: targetUser.role || 'agent',
      assigned_locations: targetUser.assigned_locations || [],
      assigned_property_types: targetUser.assigned_property_types || [],
      isActive: targetUser.is_active,
      newPassword: '',
    });
    setIsEditModalOpen(true);
  };

  const handleUpdateUser = async (e) => {
    e.preventDefault();
    if (!selectedUser) return;
    setError('');
    try {
      const payload = {
        full_name: editUserForm.fullName.trim(),
        email: editUserForm.email.trim(),
        phone_number: editUserForm.phone_number?.trim() || null,
        role: editUserForm.role,
        assigned_locations: editUserForm.assigned_locations,
        assigned_property_types: editUserForm.assigned_property_types,
        is_active: editUserForm.isActive,
      };
      if (editUserForm.newPassword) {
        payload.password = editUserForm.newPassword;
      }

      await axios.put(`${API_BASE_URL}/users/${selectedUser.id}`, payload);

      setSuccessMsg(`User ${selectedUser.username} updated successfully.`);
      setIsEditModalOpen(false);
      setSelectedUser(null);
      fetchUsers();
      if (onUserApproved) onUserApproved();
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update user.');
    }
  };

  const handleApproveUser = async (targetUser) => {
    try {
      await axios.post(`${API_BASE_URL}/users/${targetUser.id}/approve`);
      setSuccessMsg(`User @${targetUser.username} approved and activated!`);
      fetchUsers();
      if (onUserApproved) onUserApproved();
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to approve user.');
    }
  };

  const handleRejectUser = async (targetUser) => {
    if (!window.confirm(`Are you sure you want to deactivate / reject registration for @${targetUser.username}?`)) return;
    try {
      await axios.post(`${API_BASE_URL}/users/${targetUser.id}/reject`);
      setSuccessMsg(`User @${targetUser.username} registration deactivated.`);
      fetchUsers();
      if (onUserApproved) onUserApproved();
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to reject user.');
    }
  };

  const handleDeleteUser = async (targetUser) => {
    if (targetUser.id === currentUser?.id) {
      alert('You cannot delete your own logged-in admin account.');
      return;
    }

    if (!window.confirm(`Are you sure you want to permanently delete user "${targetUser.username}"?`)) {
      return;
    }

    try {
      await axios.delete(`${API_BASE_URL}/users/${targetUser.id}`);
      setSuccessMsg(`User ${targetUser.username} deleted.`);
      fetchUsers();
      if (onUserApproved) onUserApproved();
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete user.');
    }
  };

  if (!isAdmin) {
    return (
      <div className="empty-state">
        <ShieldAlert size={54} style={{ color: '#ea4335' }} />
        <h2>Access Restricted</h2>
        <p>You must have an <strong>Administrator</strong> role to manage database user accounts.</p>
      </div>
    );
  }

  const filteredUsers = users.filter((u) => {
    const matchesSearch =
      (u.full_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (u.username || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (u.email || '').toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = roleFilter === 'All' || u.role.toLowerCase() === roleFilter.toLowerCase();
    return matchesSearch && matchesRole;
  });

  const adminCount = users.filter((u) => u.role === 'admin').length;
  const agentCount = users.filter((u) => u.role === 'agent').length;
  const employeeCount = users.filter((u) => u.role === 'employee').length;
  const viewerCount = users.filter((u) => u.role === 'viewer').length;
  const pendingCount = users.filter((u) => !u.is_active).length;

  return (
    <div className="users-management-container">
      {/* Header */}
      <div className="users-header">
        <div>
          <h2 className="users-page-title" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', margin: '0 0 0.35rem 0' }}>
            <ShieldCheck size={26} color="#d4af37" /> Role-Based Access Control (RBAC)
          </h2>
          <p className="users-page-desc" style={{ color: '#64748b', fontSize: '0.88rem', margin: 0 }}>
            Manage user accounts, roles, specializations, and administrative access to the Real Estate Database.
          </p>
        </div>
        <button
          className="lux-btn-primary"
          onClick={() => setIsAddModalOpen(true)}
        >
          <UserPlus size={16} /> Add New User
        </button>
      </div>

      {/* Stats Cards */}
      <div className="rbac-stats-grid">
        <div className="rbac-stat-card">
          <div className="rbac-stat-label">Total Accounts</div>
          <div className="rbac-stat-value">{users.length}</div>
        </div>
        <div className="rbac-stat-card admin-stat">
          <div className="rbac-stat-label">Administrators</div>
          <div className="rbac-stat-value" style={{ color: '#3b82f6' }}>{adminCount}</div>
        </div>
        <div className="rbac-stat-card agent-stat">
          <div className="rbac-stat-label">Property Agents</div>
          <div className="rbac-stat-value" style={{ color: '#10b981' }}>{agentCount}</div>
        </div>
        <div className="rbac-stat-card employee-stat">
          <div className="rbac-stat-label">Employees</div>
          <div className="rbac-stat-value" style={{ color: '#f59e0b' }}>{employeeCount}</div>
        </div>
        <div className="rbac-stat-card viewer-stat">
          <div className="rbac-stat-label">Viewers</div>
          <div className="rbac-stat-value" style={{ color: '#8b5cf6' }}>{viewerCount}</div>
        </div>
        {pendingCount > 0 && (
          <div className="rbac-stat-card" style={{ borderColor: 'rgba(245, 158, 11, 0.4)', background: 'rgba(245, 158, 11, 0.08)' }}>
            <div className="rbac-stat-label" style={{ color: '#fbbf24' }}>Pending Activation</div>
            <div className="rbac-stat-value" style={{ color: '#fbbf24' }}>{pendingCount}</div>
          </div>
        )}
      </div>

      {/* Messages */}
      {successMsg && (
        <div className="alert-banner success">
          <Check size={18} /> {successMsg}
        </div>
      )}
      {error && (
        <div className="alert-banner error">
          <AlertTriangle size={18} /> {error}
        </div>
      )}

      {/* Controls: Search & Filter */}
      <div className="lux-filter-bar" style={{ marginBottom: '1.5rem' }}>
        <div className="lux-search-box" style={{ flex: 1, maxWidth: '400px' }}>
          <input
            type="text"
            className="lux-search-input"
            placeholder="Search by name, username, phone, or email..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          {searchTerm && (
            <button className="lux-search-clear" onClick={() => setSearchTerm('')}>
              <X size={14} />
            </button>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginLeft: 'auto' }}>
          <label style={{ fontSize: '0.85rem', fontWeight: 600, color: '#64748b' }}>Role Filter:</label>
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="lux-select"
          >
            <option value="All">All Roles</option>
            <option value="admin">Admin Only</option>
            <option value="agent">Agent Only</option>
            <option value="employee">Employee Only</option>
            <option value="viewer">Viewer Only</option>
          </select>

          <button
            className="lux-btn-secondary"
            onClick={fetchUsers}
            title="Refresh Users"
            style={{ padding: '0.55rem' }}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      {/* Users Table */}
      {loading ? (
        <div className="empty-state">
          <RefreshCw size={36} className="spin-icon" />
          <p>Loading user accounts...</p>
        </div>
      ) : filteredUsers.length === 0 ? (
        <div className="empty-state">
          <Users size={48} />
          <h2>No User Accounts Found</h2>
          <p>Try adjusting your search query or filters.</p>
        </div>
      ) : (
        <div className="table-responsive">
          <table className="users-table">
            <thead>
              <tr>
                <th>User Details</th>
                <th>Contact & Phone</th>
                <th>Role Tier</th>
                <th>Specialization</th>
                <th>Status</th>
                <th>Registered</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="user-identity">
                      <div className={`user-avatar ${u.role}`}>
                        {u.full_name ? u.full_name.charAt(0).toUpperCase() : u.username.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="user-name-text">
                          {u.full_name || u.username}
                          {u.id === currentUser?.id && <span className="you-badge">(You)</span>}
                        </div>
                        <div className="user-subtext">@{u.username}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div>{u.email}</div>
                    {u.phone_number ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.78rem', color: '#10b981', marginTop: '2px' }}>
                        <Phone size={12} /> {u.phone_number}
                      </div>
                    ) : (
                      <div style={{ color: '#64748b', fontSize: '0.74rem', marginTop: '2px' }}>No phone linked</div>
                    )}
                  </td>
                  <td>
                    <span className={`role-badge ${u.role}`}>
                      {u.role === 'admin' && '🛡️ ADMIN'}
                      {u.role === 'agent' && '🤝 AGENT'}
                      {u.role === 'employee' && '💼 EMPLOYEE'}
                      {u.role === 'viewer' && '👁️ VIEWER'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', maxWidth: '220px' }}>
                      {u.assigned_locations && u.assigned_locations.length > 0 ? (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px' }}>
                          {u.assigned_locations.map(loc => (
                            <span key={loc} style={{ fontSize: '0.67rem', padding: '1px 5px', background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', borderRadius: '3px' }}>
                              📍 {loc}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {u.assigned_property_types && u.assigned_property_types.length > 0 ? (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px' }}>
                          {u.assigned_property_types.map(pt => (
                            <span key={pt} style={{ fontSize: '0.67rem', padding: '1px 5px', background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', borderRadius: '3px' }}>
                              🏷️ {pt}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {(!u.assigned_locations?.length && !u.assigned_property_types?.length) && (
                        <span style={{ color: '#64748b', fontSize: '0.75rem' }}>General Pool</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <span className={`status-pill ${u.is_active ? 'active' : 'disabled'}`}>
                      {u.is_active ? '● Active' : '⏳ Pending'}
                    </span>
                  </td>
                  <td className="date-cell">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : 'N/A'}
                  </td>
                  <td>
                    <div className="actions-cell" style={{ display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'wrap' }}>
                      {!u.is_active && (
                        <>
                          <button
                            className="btn-icon approve"
                            style={{ color: '#10b981', borderColor: 'rgba(16, 185, 129, 0.4)', background: 'rgba(16, 185, 129, 0.1)', padding: '3px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '3px', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer' }}
                            onClick={() => handleApproveUser(u)}
                            title="Approve & Activate Account"
                          >
                            <Check size={14} /> Approve
                          </button>
                          <button
                            className="btn-icon reject"
                            style={{ color: '#ef4444', borderColor: 'rgba(239, 68, 68, 0.4)', background: 'rgba(239, 68, 68, 0.1)', padding: '3px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '3px', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer' }}
                            onClick={() => handleRejectUser(u)}
                            title="Reject Account"
                          >
                            <X size={14} /> Reject
                          </button>
                        </>
                      )}
                      <button
                        className="btn-icon edit"
                        onClick={() => handleOpenEdit(u)}
                        title="Edit Role & Permissions"
                      >
                        <Edit size={16} /> Edit
                      </button>
                      {u.id !== currentUser?.id && (
                        <button
                          className="btn-icon delete"
                          onClick={() => handleDeleteUser(u)}
                          title="Delete User"
                        >
                          <Trash2 size={16} /> Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add User Modal */}
      {isAddModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content auth-modal" style={{ maxWidth: '540px' }}>
            <div className="modal-header">
              <h2>Add New User Account</h2>
              <button className="close-btn" onClick={() => setIsAddModalOpen(false)}>✕</button>
            </div>

            <form onSubmit={handleCreateUser}>
              <div className="form-group">
                <label>Full Name</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. John Doe"
                  value={newUserForm.fullName}
                  onChange={(e) => setNewUserForm({ ...newUserForm, fullName: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Username</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. john_agent"
                  value={newUserForm.username}
                  onChange={(e) => setNewUserForm({ ...newUserForm, username: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Email Address</label>
                <input
                  type="email"
                  className="form-input"
                  placeholder="e.g. john@bentongland.com.my"
                  value={newUserForm.email}
                  onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>WhatsApp Phone Number (for AI RBAC & Hot Lead Routing)</label>
                <input
                  type="tel"
                  className="form-input"
                  placeholder="e.g. +60123456789"
                  value={newUserForm.phone_number}
                  onChange={(e) => setNewUserForm({ ...newUserForm, phone_number: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>Assigned Role</label>
                <select
                  className="form-input"
                  value={newUserForm.role}
                  onChange={(e) => setNewUserForm({ ...newUserForm, role: e.target.value })}
                >
                  <option value="admin">Administrator (Full DB & User Access)</option>
                  <option value="agent">Property Agent (Manage Leads & Properties)</option>
                  <option value="employee">Employee (Operations & Handover Leads)</option>
                  <option value="viewer">Viewer (Read-Only Access)</option>
                </select>
              </div>

              {/* Specialization: Locations */}
              <div className="form-group">
                <label style={{ display: 'block', marginBottom: '4px' }}>Assigned Locations (Handover Specialization)</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {ALL_LOCATIONS.map((loc) => {
                    const isSelected = newUserForm.assigned_locations.includes(loc);
                    return (
                      <button
                        key={loc}
                        type="button"
                        onClick={() => {
                          const next = isSelected
                            ? newUserForm.assigned_locations.filter((l) => l !== loc)
                            : [...newUserForm.assigned_locations, loc];
                          setNewUserForm({ ...newUserForm, assigned_locations: next });
                        }}
                        style={{
                          fontSize: '0.76rem',
                          padding: '4px 9px',
                          borderRadius: '6px',
                          border: isSelected ? '1px solid #3b82f6' : '1px solid #334155',
                          background: isSelected ? 'rgba(59, 130, 246, 0.25)' : 'rgba(255, 255, 255, 0.04)',
                          color: isSelected ? '#93c5fd' : '#94a3b8',
                          cursor: 'pointer',
                        }}
                      >
                        {isSelected ? '✓ ' : '+ '} {loc}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Specialization: Property Types */}
              <div className="form-group">
                <label style={{ display: 'block', marginBottom: '4px' }}>Assigned Property Types (Handover Specialization)</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {ALL_PROPERTY_TYPES.map((pt) => {
                    const isSelected = newUserForm.assigned_property_types.includes(pt);
                    return (
                      <button
                        key={pt}
                        type="button"
                        onClick={() => {
                          const next = isSelected
                            ? newUserForm.assigned_property_types.filter((p) => p !== pt)
                            : [...newUserForm.assigned_property_types, pt];
                          setNewUserForm({ ...newUserForm, assigned_property_types: next });
                        }}
                        style={{
                          fontSize: '0.76rem',
                          padding: '4px 9px',
                          borderRadius: '6px',
                          border: isSelected ? '1px solid #a855f7' : '1px solid #334155',
                          background: isSelected ? 'rgba(168, 85, 247, 0.25)' : 'rgba(255, 255, 255, 0.04)',
                          color: isSelected ? '#d8b4fe' : '#94a3b8',
                          cursor: 'pointer',
                        }}
                      >
                        {isSelected ? '✓ ' : '+ '} {pt}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="form-group">
                <label>Initial Password</label>
                <input
                  type="password"
                  className="form-input"
                  placeholder="Minimum 6 characters"
                  value={newUserForm.password}
                  onChange={(e) => setNewUserForm({ ...newUserForm, password: e.target.value })}
                  required
                />
              </div>

              <div className="form-group-checkbox">
                <label>
                  <input
                    type="checkbox"
                    checked={newUserForm.isActive}
                    onChange={(e) => setNewUserForm({ ...newUserForm, isActive: e.target.checked })}
                  />
                  <span>Account Active Immediately</span>
                </label>
              </div>

              <div className="modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setIsAddModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Create User
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {isEditModalOpen && selectedUser && (
        <div className="modal-overlay">
          <div className="modal-content auth-modal" style={{ maxWidth: '540px' }}>
            <div className="modal-header">
              <h2>Edit User: @{selectedUser.username}</h2>
              <button className="close-btn" onClick={() => setIsEditModalOpen(false)}>✕</button>
            </div>

            <form onSubmit={handleUpdateUser}>
              <div className="form-group">
                <label>Full Name</label>
                <input
                  type="text"
                  className="form-input"
                  value={editUserForm.fullName}
                  onChange={(e) => setEditUserForm({ ...editUserForm, fullName: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Email Address</label>
                <input
                  type="email"
                  className="form-input"
                  value={editUserForm.email}
                  onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>WhatsApp Phone Number (for AI RBAC & Hot Lead Routing)</label>
                <input
                  type="tel"
                  className="form-input"
                  placeholder="e.g. +60123456789"
                  value={editUserForm.phone_number}
                  onChange={(e) => setEditUserForm({ ...editUserForm, phone_number: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>Role</label>
                <select
                  className="form-input"
                  value={editUserForm.role}
                  onChange={(e) => setEditUserForm({ ...editUserForm, role: e.target.value })}
                >
                  <option value="admin">Administrator (Full DB & User Access)</option>
                  <option value="agent">Property Agent (Manage Leads & Properties)</option>
                  <option value="employee">Employee (Operations & Handover Leads)</option>
                  <option value="viewer">Viewer (Read-Only Access)</option>
                </select>
              </div>

              {/* Specialization: Locations */}
              <div className="form-group">
                <label style={{ display: 'block', marginBottom: '4px' }}>Assigned Locations (Handover Specialization)</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {ALL_LOCATIONS.map((loc) => {
                    const isSelected = editUserForm.assigned_locations.includes(loc);
                    return (
                      <button
                        key={loc}
                        type="button"
                        onClick={() => {
                          const next = isSelected
                            ? editUserForm.assigned_locations.filter((l) => l !== loc)
                            : [...editUserForm.assigned_locations, loc];
                          setEditUserForm({ ...editUserForm, assigned_locations: next });
                        }}
                        style={{
                          fontSize: '0.76rem',
                          padding: '4px 9px',
                          borderRadius: '6px',
                          border: isSelected ? '1px solid #3b82f6' : '1px solid #334155',
                          background: isSelected ? 'rgba(59, 130, 246, 0.25)' : 'rgba(255, 255, 255, 0.04)',
                          color: isSelected ? '#93c5fd' : '#94a3b8',
                          cursor: 'pointer',
                        }}
                      >
                        {isSelected ? '✓ ' : '+ '} {loc}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Specialization: Property Types */}
              <div className="form-group">
                <label style={{ display: 'block', marginBottom: '4px' }}>Assigned Property Types (Handover Specialization)</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {ALL_PROPERTY_TYPES.map((pt) => {
                    const isSelected = editUserForm.assigned_property_types.includes(pt);
                    return (
                      <button
                        key={pt}
                        type="button"
                        onClick={() => {
                          const next = isSelected
                            ? editUserForm.assigned_property_types.filter((p) => p !== pt)
                            : [...editUserForm.assigned_property_types, pt];
                          setEditUserForm({ ...editUserForm, assigned_property_types: next });
                        }}
                        style={{
                          fontSize: '0.76rem',
                          padding: '4px 9px',
                          borderRadius: '6px',
                          border: isSelected ? '1px solid #a855f7' : '1px solid #334155',
                          background: isSelected ? 'rgba(168, 85, 247, 0.25)' : 'rgba(255, 255, 255, 0.04)',
                          color: isSelected ? '#d8b4fe' : '#94a3b8',
                          cursor: 'pointer',
                        }}
                      >
                        {isSelected ? '✓ ' : '+ '} {pt}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="form-group">
                <label>Reset Password (Optional - leave blank to keep unchanged)</label>
                <input
                  type="password"
                  className="form-input"
                  placeholder="Enter new password"
                  value={editUserForm.newPassword}
                  onChange={(e) => setEditUserForm({ ...editUserForm, newPassword: e.target.value })}
                />
              </div>

              <div className="form-group-checkbox">
                <label>
                  <input
                    type="checkbox"
                    checked={editUserForm.isActive}
                    onChange={(e) => setEditUserForm({ ...editUserForm, isActive: e.target.checked })}
                  />
                  <span>Account Active (Allowed to sign in)</span>
                </label>
              </div>

              <div className="modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setIsEditModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default UsersManagement;
