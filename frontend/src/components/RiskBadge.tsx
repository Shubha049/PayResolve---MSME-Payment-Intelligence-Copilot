import React, { useState, useEffect } from 'react';
import { AlertTriangle, TrendingUp, TrendingDown, Info, X, RefreshCw } from 'lucide-react';
import { riskAPI } from '../api/endpoints';

interface RiskFactor {
  name: string;
  contribution: number;
  label: string;
}

interface RiskAssessment {
  id: string;
  risk_score: number;
  risk_category: 'Low' | 'Medium' | 'High';
  top_factors: RiskFactor[];
  scoring_method: 'heuristic' | 'ml';
  model_version: string;
  created_at: string;
}

interface RiskBadgeProps {
  invoiceId: string;
  inline?: boolean; // If true, shows compact badge. If false, shows detailed view
}

const categoryColors = {
  Low: 'bg-green-500/10 text-green-400 border-green-500/30',
  Medium: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
  High: 'bg-red-500/10 text-red-400 border-red-500/30',
};

const categoryIcons = {
  Low: <TrendingDown size={14} />,
  Medium: <AlertTriangle size={14} />,
  High: <AlertTriangle size={14} />,
};

export default function RiskBadge({ invoiceId, inline = true }: RiskBadgeProps) {
  const [assessment, setAssessment] = useState<RiskAssessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDetail, setShowDetail] = useState(false);
  const [rescoring, setRescoring] = useState(false);
  const [error, setError] = useState('');

  const loadRisk = async () => {
    try {
      setLoading(true);
      setError('');
      const res = await riskAPI.getInvoiceRisk(invoiceId);
      setAssessment(res.data);
    } catch (err) {
      setError('Unable to load risk score');
      console.error('Risk load error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleRescore = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setRescoring(true);
      const res = await riskAPI.rescoreInvoice(invoiceId);
      setAssessment(res.data);
    } catch (err) {
      console.error('Rescore error:', err);
    } finally {
      setRescoring(false);
    }
  };

  useEffect(() => {
    loadRisk();
  }, [invoiceId]);

  if (loading) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs border border-surface-700 bg-surface-800/50 text-surface-400">
        <div className="w-2 h-2 rounded-full bg-surface-600 animate-pulse" />
        <span>Loading...</span>
      </div>
    );
  }

  if (error || !assessment) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs border border-surface-700 bg-surface-800/50 text-surface-500">
        <Info size={12} />
        <span>N/A</span>
      </div>
    );
  }

  const category = assessment.risk_category;
  const isHeuristic = assessment.scoring_method === 'heuristic';

  if (inline) {
    return (
      <>
        <button
          onClick={() => setShowDetail(true)}
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border transition-all hover:brightness-110 ${categoryColors[category]}`}
          title={`Risk Score: ${(assessment.risk_score * 100).toFixed(0)}%`}
        >
          {categoryIcons[category]}
          <span>{category}</span>
          {isHeuristic && (
            <span className="text-[10px] opacity-60" title="Provisional heuristic score">
              †
            </span>
          )}
        </button>

        {/* Detail Drawer */}
        {showDetail && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
            <div className="bg-surface-800 border border-surface-700 rounded-lg shadow-2xl w-full max-w-lg mx-4 animate-slide-up">
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-surface-700">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${categoryColors[category].split(' ')[0]}`}>
                    {categoryIcons[category]}
                  </div>
                  <div>
                    <h3 className="font-semibold text-surface-50">Risk Assessment</h3>
                    <p className="text-xs text-surface-400">
                      Score: {(assessment.risk_score * 100).toFixed(1)}% — {category} Risk
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setShowDetail(false)}
                  className="p-1 rounded hover:bg-surface-700 text-surface-400 hover:text-surface-200 transition"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Content */}
              <div className="p-4 space-y-4 max-h-[60vh] overflow-y-auto">
                {/* Method Badge */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-surface-400">Scoring Method:</span>
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${
                        isHeuristic
                          ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                          : 'bg-purple-500/10 text-purple-400 border-purple-500/30'
                      }`}
                    >
                      {isHeuristic ? 'Heuristic (Provisional)' : 'ML Model'}
                    </span>
                  </div>
                  <button
                    onClick={handleRescore}
                    disabled={rescoring}
                    className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs bg-surface-700 hover:bg-surface-600 text-surface-200 transition disabled:opacity-50"
                    title="Recalculate risk score"
                  >
                    <RefreshCw size={12} className={rescoring ? 'animate-spin' : ''} />
                    {rescoring ? 'Rescoring...' : 'Rescore'}
                  </button>
                </div>

                {isHeuristic && (
                  <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300">
                    <strong>Provisional Score:</strong> This customer has limited payment history. The score is
                    calculated using a transparent rule-based heuristic. Once more payment data is available,
                    ML-based scoring will be used for higher accuracy.
                  </div>
                )}

                {/* Contributing Factors */}
                <div>
                  <h4 className="text-sm font-medium text-surface-200 mb-2">Contributing Factors</h4>
                  <div className="space-y-2">
                    {assessment.top_factors?.map((factor, idx) => {
                      const isIncreasing = factor.contribution > 0;
                      return (
                        <div
                          key={idx}
                          className="flex items-start gap-2 p-2 rounded bg-surface-900/50 border border-surface-700"
                        >
                          <div
                            className={`mt-0.5 ${
                              isIncreasing ? 'text-red-400' : 'text-green-400'
                            }`}
                          >
                            {isIncreasing ? (
                              <TrendingUp size={14} />
                            ) : (
                              <TrendingDown size={14} />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs text-surface-300 leading-relaxed">
                              {factor.label}
                            </p>
                            <p className="text-[10px] text-surface-500 mt-0.5">
                              Impact: {Math.abs(factor.contribution * 100).toFixed(1)}%
                            </p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Metadata */}
                <div className="pt-3 border-t border-surface-700 text-[10px] text-surface-500 space-y-1">
                  <div>Model Version: {assessment.model_version}</div>
                  <div>
                    Assessed: {new Date(assessment.created_at).toLocaleString('en-IN', {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div className="p-4 border-t border-surface-700 bg-surface-900/30">
                <button
                  onClick={() => setShowDetail(false)}
                  className="w-full px-3 py-2 rounded bg-primary-600 hover:bg-primary-500 text-white text-sm font-medium transition"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  // Non-inline detailed view (for future use in dedicated risk pages)
  return (
    <div className="p-4 rounded-lg border border-surface-700 bg-surface-800">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-medium text-surface-100">Risk Assessment</h4>
        <span className={`px-2 py-1 rounded text-xs font-medium ${categoryColors[category]}`}>
          {category}
        </span>
      </div>
      <p className="text-sm text-surface-400">
        Score: {(assessment.risk_score * 100).toFixed(1)}%
      </p>
    </div>
  );
}
