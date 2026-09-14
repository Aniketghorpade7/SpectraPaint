import { useState } from 'react';

export interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onQualityTierChange: (tier: string) => void;
  currentQualityTier: string;
}

export function SettingsModal({
  isOpen,
  onClose,
  onQualityTierChange,
  currentQualityTier,
}: SettingsModalProps) {
  const [qualityTier, setQualityTier] = useState(currentQualityTier);
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onQualityTierChange(qualityTier);
      onClose();
    } catch (error) {
      console.error('Failed to save quality tier:', error);
      // In a real app, we would show an error message
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="settings-modal-backdrop" onClick={onClose}>
      <div className="settings-modal-content" onClick={e => e.stopPropagation()}>
        <div className="settings-modal-header">
          <h2 className="settings-modal-title">Settings</h2>
          <button
            className="settings-modal-close"
            onClick={onClose}
            aria-label="Close settings"
          >
            ×
          </button>
        </div>
        <div className="settings-modal-body">
          <div className="settings-modal-section">
            <label className="settings-modal-label" htmlFor="quality-tier">
              Quality Tier
            </label>
            <div className="settings-modal-control">
              <select
                id="quality-tier"
                value={qualityTier}
                onChange={(e) => setQualityTier(e.target.value)}
                disabled={isSaving}
              >
                <option value="faster">Faster (lower quality)</option>
                <option value="better">Better quality (slower)</option>
              </select>
            </div>
            <p className="settings-modal-description">
              Choose how SpectraPaint balances speed and quality. Faster settings
              use less accurate models for quicker results. Better quality uses
              more accurate models but takes longer.
            </p>
          </div>
        </div>
        <div className="settings-modal-footer">
          <button
            className="button"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="button button--primary"
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}