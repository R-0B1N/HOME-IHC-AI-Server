import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { UserPlus, User, Mail, Lock, Shield, ArrowLeft, CheckCircle2, Building2, Sparkles, Phone, Briefcase, Clock } from 'lucide-react';

function RegisterPage({ onSwitchToLogin }) {
  const { register } = useAuth();
  const [formData, setFormData] = useState({
    fullName: '',
    username: '',
    email: '',
    phoneNumber: '',
    password: '',
    confirmPassword: '',
    role: 'agent',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [registeredData, setRegisteredData] = useState(null);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleRoleSelect = (role) => {
    setFormData({ ...formData, role });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match. Please re-enter.');
      return;
    }

    if (formData.password.length < 6) {
      setError('Password must contain at least 6 characters.');
      return;
    }

    setLoading(true);
    const result = await register({
      full_name: formData.fullName.trim(),
      username: formData.username.trim(),
      email: formData.email.trim(),
      phone_number: formData.phoneNumber.trim() || undefined,
      password: formData.password,
      role: formData.role,
    });
    setLoading(false);

    if (result.success) {
      setRegisteredData(result.data);
    } else {
      setError(result.error);
    }
  };

  return (
    <div className="lux-auth-viewport">
      <div className="lux-ambient-glow gold"></div>
      <div className="lux-ambient-glow sapphire"></div>

      <div className="lux-auth-shell register-shell">
        <div className="lux-card">
          <div className="lux-header">
            <div className="lux-emblem-wrap">
              <div className="lux-emblem">
                <UserPlus size={24} className="lux-emblem-icon" />
              </div>
              <div className="lux-emblem-ring"></div>
            </div>

            <div className="lux-eyebrow">
              <Sparkles size={13} className="lux-sparkle" />
              <span>ACCESS PROVISIONING</span>
            </div>

            <h1 className="lux-title">Create Account</h1>
            <p className="lux-desc">Configure your profile & access level</p>
          </div>

          {error && (
            <div className="lux-alert-error">
              <div className="lux-alert-indicator"></div>
              <span>{error}</span>
            </div>
          )}

          {registeredData ? (
            <div className="lux-success-panel">
              <div className="lux-success-icon-wrap">
                {registeredData.is_active ? <CheckCircle2 size={38} /> : <Clock size={38} className="text-amber-500" />}
              </div>
              <h2 className="lux-success-title">
                {registeredData.is_active ? "Account Created" : "Registration Pending Approval"}
              </h2>
              <p className="lux-success-desc">
                {registeredData.is_active ? (
                  <>
                    Account <strong>@{registeredData.username}</strong> has been provisioned with{' '}
                    <span className={`lux-role-pill ${registeredData.role}`}>{registeredData.role.toUpperCase()}</span> tier access.
                  </>
                ) : (
                  <>
                    Account <strong>@{registeredData.username}</strong> has been registered with{' '}
                    <span className={`lux-role-pill ${registeredData.role}`}>{registeredData.role.toUpperCase()}</span> role request.
                    <br />
                    <span style={{ color: '#eab308', display: 'inline-block', marginTop: '8px' }}>
                      ⏳ An administrator must approve and activate your account before you can sign in.
                    </span>
                  </>
                )}
              </p>
              <button
                type="button"
                className="lux-btn-primary"
                onClick={onSwitchToLogin}
              >
                Proceed to Sign In
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="lux-form">
              <div className="lux-fields-grid">
                <div className="lux-field-group">
                  <label className="lux-label">Full Name</label>
                  <div className="lux-input-box">
                    <User size={17} className="lux-field-icon" />
                    <input
                      type="text"
                      name="fullName"
                      className="lux-input"
                      placeholder="e.g. Irene Leong"
                      value={formData.fullName}
                      onChange={handleChange}
                      required
                    />
                  </div>
                </div>

                <div className="lux-field-group">
                  <label className="lux-label">Username</label>
                  <div className="lux-input-box">
                    <User size={17} className="lux-field-icon" />
                    <input
                      type="text"
                      name="username"
                      className="lux-input"
                      placeholder="e.g. irene_agent"
                      value={formData.username}
                      onChange={handleChange}
                      required
                    />
                  </div>
                </div>
              </div>

              <div className="lux-fields-grid">
                <div className="lux-field-group">
                  <label className="lux-label">Corporate Email</label>
                  <div className="lux-input-box">
                    <Mail size={17} className="lux-field-icon" />
                    <input
                      type="email"
                      name="email"
                      className="lux-input"
                      placeholder="e.g. irene@bentongland.com.my"
                      value={formData.email}
                      onChange={handleChange}
                      required
                    />
                  </div>
                </div>

                <div className="lux-field-group">
                  <label className="lux-label">WhatsApp Phone Number</label>
                  <div className="lux-input-box">
                    <Phone size={17} className="lux-field-icon" />
                    <input
                      type="tel"
                      name="phoneNumber"
                      className="lux-input"
                      placeholder="e.g. +60123456789"
                      value={formData.phoneNumber}
                      onChange={handleChange}
                    />
                  </div>
                </div>
              </div>

              {/* Role Tier Selector Cards */}
              <div className="lux-field-group">
                <label className="lux-label">Select Role Tier</label>
                <div className="lux-role-cards-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))' }}>
                  <div
                    className={`lux-role-option ${formData.role === 'admin' ? 'selected' : ''}`}
                    onClick={() => handleRoleSelect('admin')}
                  >
                    <div className="lux-role-option-header">
                      <Shield size={16} />
                      <span className="lux-role-option-title">Admin</span>
                    </div>
                    <span className="lux-role-option-sub">Full system & user controls</span>
                  </div>

                  <div
                    className={`lux-role-option ${formData.role === 'agent' ? 'selected' : ''}`}
                    onClick={() => handleRoleSelect('agent')}
                  >
                    <div className="lux-role-option-header">
                      <Building2 size={16} />
                      <span className="lux-role-option-title">Agent</span>
                    </div>
                    <span className="lux-role-option-sub">Specialized lead routing</span>
                  </div>

                  <div
                    className={`lux-role-option ${formData.role === 'employee' ? 'selected' : ''}`}
                    onClick={() => handleRoleSelect('employee')}
                  >
                    <div className="lux-role-option-header">
                      <Briefcase size={16} />
                      <span className="lux-role-option-title">Employee</span>
                    </div>
                    <span className="lux-role-option-sub">Staff operations & leads</span>
                  </div>

                  <div
                    className={`lux-role-option ${formData.role === 'viewer' ? 'selected' : ''}`}
                    onClick={() => handleRoleSelect('viewer')}
                  >
                    <div className="lux-role-option-header">
                      <User size={16} />
                      <span className="lux-role-option-title">Viewer</span>
                    </div>
                    <span className="lux-role-option-sub">Read-only listings & leads</span>
                  </div>
                </div>
              </div>

              <div className="lux-fields-grid">
                <div className="lux-field-group">
                  <label className="lux-label">Password</label>
                  <div className="lux-input-box">
                    <Lock size={17} className="lux-field-icon" />
                    <input
                      type="password"
                      name="password"
                      className="lux-input"
                      placeholder="Min 6 chars"
                      value={formData.password}
                      onChange={handleChange}
                      required
                    />
                  </div>
                </div>

                <div className="lux-field-group">
                  <label className="lux-label">Confirm Password</label>
                  <div className="lux-input-box">
                    <Lock size={17} className="lux-field-icon" />
                    <input
                      type="password"
                      name="confirmPassword"
                      className="lux-input"
                      placeholder="Re-enter password"
                      value={formData.confirmPassword}
                      onChange={handleChange}
                      required
                    />
                  </div>
                </div>
              </div>

              <button
                type="submit"
                className="lux-btn-primary"
                disabled={loading}
              >
                {loading ? (
                  <span className="lux-btn-loading">
                    <span className="lux-spinner"></span>
                    Provisioning Account...
                  </span>
                ) : (
                  <>
                    <span>Complete Registration</span>
                    <Sparkles size={16} className="lux-btn-arrow" />
                  </>
                )}
              </button>
            </form>
          )}

          <div className="lux-footer">
            <span className="lux-footer-text">Already registered?</span>
            <button
              type="button"
              className="lux-btn-link"
              onClick={onSwitchToLogin}
            >
              <ArrowLeft size={14} /> Back to Sign In
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default RegisterPage;
