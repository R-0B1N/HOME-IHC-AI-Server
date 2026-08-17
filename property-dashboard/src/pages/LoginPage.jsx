import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Shield, Lock, User, Eye, EyeOff, ArrowRight, Sparkles, Building2 } from 'lucide-react';

function LoginPage({ onSwitchToRegister }) {
  const { login } = useAuth();
  const [usernameOrEmail, setUsernameOrEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!usernameOrEmail.trim() || !password) {
      setError('Please enter your account identifier and password.');
      return;
    }

    setLoading(true);
    const result = await login(usernameOrEmail.trim(), password);
    setLoading(false);

    if (!result.success) {
      setError(result.error);
    }
  };

  return (
    <div className="lux-auth-viewport">
      {/* Ambient background glows */}
      <div className="lux-ambient-glow gold"></div>
      <div className="lux-ambient-glow sapphire"></div>

      <div className="lux-auth-shell">
        <div className="lux-card">
          {/* Header & Emblem */}
          <div className="lux-header">
            <div className="lux-emblem-wrap">
              <div className="lux-emblem">
                <Building2 size={26} className="lux-emblem-icon" />
              </div>
              <div className="lux-emblem-ring"></div>
            </div>

            <div className="lux-eyebrow">
              <Sparkles size={13} className="lux-sparkle" />
              <span>ESTATE INTELLIGENCE & CRM</span>
            </div>

            <h1 className="lux-title">BentongLand Portal</h1>
            <p className="lux-desc">Role-Based Database & AI Orchestration System</p>
          </div>

          {/* Error Notice */}
          {error && (
            <div className="lux-alert-error">
              <div className="lux-alert-indicator"></div>
              <span>{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="lux-form">
            <div className="lux-field-group">
              <label className="lux-label">Username or Email</label>
              <div className="lux-input-box">
                <User size={17} className="lux-field-icon" />
                <input
                  type="text"
                  className="lux-input"
                  placeholder="Enter your username or email"
                  value={usernameOrEmail}
                  onChange={(e) => setUsernameOrEmail(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
            </div>

            <div className="lux-field-group">
              <label className="lux-label">Password</label>
              <div className="lux-input-box">
                <Lock size={17} className="lux-field-icon" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="lux-input"
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="lux-eye-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  tabIndex={-1}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
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
                  Authenticating...
                </span>
              ) : (
                <>
                  <span>Sign In to Console</span>
                  <ArrowRight size={16} className="lux-btn-arrow" />
                </>
              )}
            </button>
          </form>

          {/* Footer Navigation */}
          <div className="lux-footer">
            <span className="lux-footer-text">Need an internal account?</span>
            <button
              type="button"
              className="lux-btn-link"
              onClick={onSwitchToRegister}
            >
              Request Access / Register
            </button>
          </div>
        </div>

        {/* Security watermark */}
        <div className="lux-security-watermark">
          <Shield size={12} />
          <span>Protected by AES-256 JWT RBAC Session Security</span>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
