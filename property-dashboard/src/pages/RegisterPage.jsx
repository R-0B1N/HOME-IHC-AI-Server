import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { UserPlus, User, Mail, Lock, Shield, ArrowLeft, CheckCircle2 } from 'lucide-react';

function RegisterPage({ onSwitchToLogin }) {
  const { register } = useAuth();
  const [formData, setFormData] = useState({
    fullName: '',
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
    role: 'agent',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    if (formData.password.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }

    setLoading(true);
    const result = await register({
      full_name: formData.fullName.trim(),
      username: formData.username.trim(),
      email: formData.email.trim(),
      password: formData.password,
      role: formData.role,
    });
    setLoading(false);

    if (result.success) {
      setSuccess(true);
    } else {
      setError(result.error);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <div className="auth-header">
          <div className="auth-logo-badge">
            <UserPlus size={36} className="auth-icon" />
          </div>
          <h1 className="auth-title">Create Account</h1>
          <p className="auth-subtitle">Assign Role & Setup Access</p>
        </div>

        {error && (
          <div className="auth-error-banner">
            <span>{error}</span>
          </div>
        )}

        {success ? (
          <div className="auth-success-card">
            <CheckCircle2 size={48} className="auth-success-icon" />
            <h2>Account Created!</h2>
            <p>
              Account for <strong>{formData.username}</strong> with role{' '}
              <span className={`role-badge ${formData.role}`}>{formData.role.toUpperCase()}</span> has been registered.
            </p>
            <button
              type="button"
              className="auth-submit-btn"
              onClick={onSwitchToLogin}
            >
              Go to Login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="auth-form">
            <div className="auth-form-group">
              <label className="auth-label">Full Name</label>
              <div className="auth-input-wrapper">
                <User size={18} className="auth-input-icon" />
                <input
                  type="text"
                  name="fullName"
                  className="auth-input"
                  placeholder="e.g. Irene Leong"
                  value={formData.fullName}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Username</label>
              <div className="auth-input-wrapper">
                <User size={18} className="auth-input-icon" />
                <input
                  type="text"
                  name="username"
                  className="auth-input"
                  placeholder="e.g. irene_agent"
                  value={formData.username}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Email Address</label>
              <div className="auth-input-wrapper">
                <Mail size={18} className="auth-input-icon" />
                <input
                  type="email"
                  name="email"
                  className="auth-input"
                  placeholder="e.g. irene@bentongland.com.my"
                  value={formData.email}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Account Role (Access Tier)</label>
              <div className="auth-input-wrapper">
                <Shield size={18} className="auth-input-icon" />
                <select
                  name="role"
                  className="auth-select"
                  value={formData.role}
                  onChange={handleChange}
                  required
                >
                  <option value="admin">Administrator (Full Access & User Mgmt)</option>
                  <option value="agent">Property Agent (Manage Leads & Properties)</option>
                  <option value="viewer">Viewer (Read-Only Access)</option>
                </select>
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Password</label>
              <div className="auth-input-wrapper">
                <Lock size={18} className="auth-input-icon" />
                <input
                  type="password"
                  name="password"
                  className="auth-input"
                  placeholder="Minimum 6 characters"
                  value={formData.password}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Confirm Password</label>
              <div className="auth-input-wrapper">
                <Lock size={18} className="auth-input-icon" />
                <input
                  type="password"
                  name="confirmPassword"
                  className="auth-input"
                  placeholder="Re-enter password"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              className="auth-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <span className="auth-spinner">Creating Account...</span>
              ) : (
                <>
                  <UserPlus size={18} /> Register Account
                </>
              )}
            </button>
          </form>
        )}

        <div className="auth-footer">
          <p>Already have an account?</p>
          <button
            type="button"
            className="auth-link-btn"
            onClick={onSwitchToLogin}
          >
            <ArrowLeft size={16} /> Back to Sign In
          </button>
        </div>
      </div>
    </div>
  );
}

export default RegisterPage;
