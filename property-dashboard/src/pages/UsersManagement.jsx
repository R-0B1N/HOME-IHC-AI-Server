import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { 
  Users, UserPlus, Shield, ShieldCheck, ShieldAlert, 
  Trash2, Edit, Check, X, Search, Lock, RefreshCw, AlertTriangle 
} from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

function UsersManagement() {
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
    password: '',
    fullName: '',
    role: 'agent',
    isActive: true,
  });

  const [editUserForm, setEditUserForm] = useState({
    fullName: '',
    email: '',
    role: 'agent',
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
        password: newUserForm.password,
        full_name: newUserForm.fullName.trim(),
        role: newUserForm.role,
        is_active: newUserForm.isActive,
      });

      setSuccessMsg(`User ${newUserForm.username} created successfully.`);
      setIsAddModalOpen(false);
      setNewUserForm({
        username: '',
        email: '',
        password: '',
        fullName: '',
        role: 'agent',
        isActive: true,
      });
      fetchUsers();
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
      role: targetUser.role || 'agent',
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
        role: editUserForm.role,
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
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update user.');
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
  const viewerCount = users.filter((u) => u.role === 'viewer').length;

  return (
    <div className="users-management-container">
      {/* Header */}
      <div className="users-header">
        <div>
          <h2 className="users-page-title" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', margin: '0 0 0.35rem 0' }}>
            <ShieldCheck size={26} color="#d4af37" /> Role-Based Access Control (RBAC)
          </h2>
          <p className="users-page-desc" style={{ color: '#64748b', fontSize: '0.88rem', margin: 0 }}>
            Manage user accounts, roles, and administrative access to the Real Estate Database.
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
        <div className="rbac-stat-card viewer-stat">
          <div className="rbac-stat-label">Viewers</div>
          <div className="rbac-stat-value" style={{ color: '#8b5cf6' }}>{viewerCount}</div>
        </div>
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
            placeholder="Search by name, username, or email..."
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
                <th>Email</th>
                <th>Role Tier</th>
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
                  <td>{u.email}</td>
                  <td>
                    <span className={`role-badge ${u.role}`}>
                      {u.role === 'admin' && '🛡️ '}
                      {u.role === 'agent' && '🤝 '}
                      {u.role === 'viewer' && '👁️ '}
                      {u.role.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <span className={`status-pill ${u.is_active ? 'active' : 'disabled'}`}>
                      {u.is_active ? '● Active' : '○ Disabled'}
                    </span>
                  </td>
                  <td className="date-cell">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : 'N/A'}
                  </td>
                  <td>
                    <div className="actions-cell">
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
          <div className="modal-content auth-modal">
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
                <label>Assigned Role</label>
                <select
                  className="form-input"
                  value={newUserForm.role}
                  onChange={(e) => setNewUserForm({ ...newUserForm, role: e.target.value })}
                >
                  <option value="admin">Administrator (Full DB & User Access)</option>
                  <option value="agent">Property Agent (Manage Leads & Properties)</option>
                  <option value="viewer">Viewer (Read-Only Access)</option>
                </select>
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
          <div className="modal-content auth-modal">
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
                <label>Role</label>
                <select
                  className="form-input"
                  value={editUserForm.role}
                  onChange={(e) => setEditUserForm({ ...editUserForm, role: e.target.value })}
                >
                  <option value="admin">Administrator (Full DB & User Access)</option>
                  <option value="agent">Property Agent (Manage Leads & Properties)</option>
                  <option value="viewer">Viewer (Read-Only Access)</option>
                </select>
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
