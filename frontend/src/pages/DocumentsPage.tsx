import { useState, useEffect, useCallback, useRef, type DragEvent } from 'react';
import {
  UploadCloud, FileText, CheckCircle2, Clock, XCircle,
  Trash2, Eye, Filter, RefreshCw, Layers, ShieldCheck, Quote,
  X, AlertCircle, Check, Copy
} from 'lucide-react';
import { documentsAPI } from '../api/endpoints';

interface DocumentListItem {
  id: string;
  original_name: string;
  doc_type: string;
  status: string;
  file_size: number;
  page_count: number | null;
  created_at: string;
}

interface EvidenceField {
  value: any;
  page: number | null;
  source_text: string | null;
  confidence: number;
  status: 'verified' | 'inferred' | 'missing';
}

interface DocumentDetail extends DocumentListItem {
  organization_id: string;
  file_name: string;
  mime_type: string;
  classification_confidence: number | null;
  extracted_fields: Record<string, EvidenceField> | null;
  error_message: string | null;
  invoice_id: string | null;
  case_id: string | null;
}

interface ChunkItem {
  id: string;
  chunk_index: number;
  chunk_text: string;
  page_number: number | null;
  char_start: number | null;
  char_end: number | null;
}

const DOC_TYPES = ['ALL', 'INVOICE', 'CONTRACT', 'PURCHASE_ORDER', 'RECEIPT', 'CORRESPONDENCE', 'UNKNOWN'];
const STATUSES = ['ALL', 'DONE', 'PROCESSING', 'PENDING', 'FAILED'];

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedType, setSelectedType] = useState('ALL');
  const [selectedStatus, setSelectedStatus] = useState('ALL');

  // Drag and drop upload
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Drawer & detail
  const [activeDoc, setActiveDoc] = useState<DocumentDetail | null>(null);
  const [activeTab, setActiveTab] = useState<'fields' | 'chunks'>('fields');
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Delete
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchDocuments = useCallback(async () => {
    try {
      setError(null);
      const params: any = {};
      if (selectedType !== 'ALL') params.doc_type = selectedType;
      if (selectedStatus !== 'ALL') params.status = selectedStatus;
      const res = await documentsAPI.list(params);
      setDocuments(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to fetch documents');
    } finally {
      setLoading(false);
    }
  }, [selectedType, selectedStatus]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Polling if any document is PENDING or PROCESSING
  useEffect(() => {
    const hasPending = documents.some(
      (d) => d.status === 'PENDING' || d.status === 'PROCESSING'
    );
    if (!hasPending) return;

    const interval = setInterval(() => {
      fetchDocuments();
    }, 3000);
    return () => clearInterval(interval);
  }, [documents, fetchDocuments]);

  // Handle file upload
  const handleUpload = async (file: File) => {
    if (!file) return;
    setUploading(true);
    setUploadProgress(`Uploading ${file.name}...`);
    try {
      const formData = new FormData();
      formData.append('file', file);
      await documentsAPI.upload(formData);
      setUploadProgress('Queued for AI extraction...');
      setTimeout(() => {
        setUploadProgress(null);
        setUploading(false);
      }, 1200);
      fetchDocuments();
    } catch (err: any) {
      setUploading(false);
      setUploadProgress(null);
      setError(err?.response?.data?.detail || 'Upload failed. Check format and size (max 20MB).');
    }
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const onDragLeave = () => {
    setIsDragging(false);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUpload(e.dataTransfer.files[0]);
    }
  };

  const openDetail = async (docId: string) => {
    setActiveTab('fields');
    setChunks([]);
    try {
      const res = await documentsAPI.get(docId);
      setActiveDoc(res.data);
    } catch (err: any) {
      setError('Could not load document details');
    }
  };

  const loadChunks = async (docId: string) => {
    setLoadingChunks(true);
    try {
      const res = await documentsAPI.getChunks(docId);
      setChunks(res.data);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoadingChunks(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingId) return;
    setIsDeleting(true);
    try {
      await documentsAPI.delete(deletingId);
      if (activeDoc?.id === deletingId) {
        setActiveDoc(null);
      }
      setDeletingId(null);
      fetchDocuments();
    } catch (err: any) {
      setError('Failed to delete document');
    } finally {
      setIsDeleting(false);
    }
  };

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(key);
    setTimeout(() => setCopiedField(null), 1800);
  };

  const renderStatusBadge = (status: string) => {
    switch (status) {
      case 'DONE':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 size={12} />
            DONE
          </span>
        );
      case 'PROCESSING':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <RefreshCw size={12} className="animate-spin" />
            PROCESSING
          </span>
        );
      case 'PENDING':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-surface-500/10 text-surface-400 border border-surface-500/20">
            <Clock size={12} className="animate-pulse" />
            PENDING
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <XCircle size={12} />
            FAILED
          </span>
        );
      default:
        return null;
    }
  };

  const renderDocTypeBadge = (type: string) => {
    const colors: Record<string, string> = {
      INVOICE: 'bg-brand-500/10 text-brand-400 border-brand-500/20',
      CONTRACT: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
      PURCHASE_ORDER: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
      RECEIPT: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
      CORRESPONDENCE: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
      UNKNOWN: 'bg-surface-500/10 text-surface-400 border-surface-500/20',
    };
    return (
      <span className={`px-2 py-0.5 rounded text-[11px] font-semibold border ${colors[type] || colors.UNKNOWN}`}>
        {type.replace('_', ' ')}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-50">Document Intelligence</h1>
          <p className="text-sm text-surface-400 mt-1">
            Upload business documents for automated verification, evidence extraction, and RAG indexing.
          </p>
        </div>
        <button
          onClick={() => fetchDocuments()}
          className="btn-secondary self-start sm:self-auto flex items-center gap-2 text-xs"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-start gap-3">
          <AlertCircle size={18} className="text-rose-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1 text-sm text-rose-300">{error}</div>
          <button onClick={() => setError(null)} className="text-rose-400 hover:text-rose-300">
            <X size={16} />
          </button>
        </div>
      )}

      {/* Drag & Drop Upload Zone */}
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative cursor-pointer border-2 border-dashed rounded-2xl p-8 transition-all duration-200 text-center ${
          isDragging
            ? 'border-brand-400 bg-brand-500/10 scale-[1.01]'
            : 'border-surface-700 bg-surface-800/60 hover:border-brand-500/50 hover:bg-surface-800'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.tiff,.tif,.csv,.xlsx,.xls"
          onChange={(e) => {
            if (e.target.files && e.target.files[0]) {
              handleUpload(e.target.files[0]);
            }
          }}
        />

        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="w-14 h-14 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center text-brand-400 shadow-inner">
            {uploading ? (
              <RefreshCw size={28} className="animate-spin text-brand-400" />
            ) : (
              <UploadCloud size={28} />
            )}
          </div>

          <div>
            <p className="text-base font-semibold text-surface-100">
              {uploading ? uploadProgress : 'Click to upload or drag & drop documents'}
            </p>
            <p className="text-xs text-surface-400 mt-1">
              Supports PDF, Word (DOCX), Images (PNG, JPG), Excel (XLSX, CSV) up to 20MB
            </p>
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface-700/60 text-[11px] text-surface-300 border border-surface-600/40">
            <ShieldCheck size={12} className="text-brand-400" />
            Zero-hallucination extraction with page-level citations
          </div>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-2">
        {/* Type pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
          <span className="text-xs font-medium text-surface-400 mr-1 flex items-center gap-1">
            <Filter size={12} /> Type:
          </span>
          {DOC_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                selectedType === type
                  ? 'bg-brand-500 text-white shadow-sm shadow-brand-500/30'
                  : 'bg-surface-800 text-surface-300 hover:bg-surface-700 border border-surface-700'
              }`}
            >
              {type.replace('_', ' ')}
            </button>
          ))}
        </div>

        {/* Status pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
          <span className="text-xs font-medium text-surface-400 mr-1">Status:</span>
          {STATUSES.map((st) => (
            <button
              key={st}
              onClick={() => setSelectedStatus(st)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                selectedStatus === st
                  ? 'bg-surface-600 text-white'
                  : 'bg-surface-800 text-surface-400 hover:bg-surface-700 border border-surface-700'
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Documents Table */}
      <div className="card overflow-hidden p-0 border border-surface-700 bg-surface-850">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-800/80 text-surface-400 text-xs font-semibold uppercase tracking-wider border-b border-surface-700">
              <tr>
                <th className="py-3.5 px-4">Document</th>
                <th className="py-3.5 px-4">Type</th>
                <th className="py-3.5 px-4">Pages</th>
                <th className="py-3.5 px-4">Size</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Uploaded</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700/60">
              {loading && documents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-surface-400">
                    <RefreshCw size={24} className="animate-spin mx-auto mb-2 text-brand-400" />
                    Loading documents...
                  </td>
                </tr>
              ) : documents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-surface-400">
                    <FileText size={32} className="mx-auto mb-3 text-surface-600" />
                    <p className="font-medium text-surface-300">No documents found</p>
                    <p className="text-xs text-surface-500 mt-1">Upload a business document above to begin</p>
                  </td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-surface-800/50 transition-colors group">
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-surface-750 border border-surface-700 flex items-center justify-center text-brand-400 group-hover:border-brand-500/40">
                          <FileText size={18} />
                        </div>
                        <div>
                          <div
                            onClick={() => openDetail(doc.id)}
                            className="font-medium text-surface-100 hover:text-brand-400 cursor-pointer transition-colors"
                          >
                            {doc.original_name}
                          </div>
                          <div className="text-[11px] text-surface-500 font-mono">ID: {doc.id.slice(0, 8)}</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3.5 px-4">{renderDocTypeBadge(doc.doc_type)}</td>
                    <td className="py-3.5 px-4 text-surface-300">{doc.page_count ? `${doc.page_count} pg` : '—'}</td>
                    <td className="py-3.5 px-4 text-surface-400 font-mono text-xs">{formatBytes(doc.file_size)}</td>
                    <td className="py-3.5 px-4">{renderStatusBadge(doc.status)}</td>
                    <td className="py-3.5 px-4 text-xs text-surface-400">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => openDetail(doc.id)}
                          title="View Extracted Evidence"
                          className="p-1.5 rounded-lg text-surface-400 hover:text-brand-400 hover:bg-surface-700 transition-colors"
                        >
                          <Eye size={16} />
                        </button>
                        <button
                          onClick={() => setDeletingId(doc.id)}
                          title="Delete Document"
                          className="p-1.5 rounded-lg text-surface-400 hover:text-rose-400 hover:bg-surface-700 transition-colors"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Document Detail Drawer */}
      {activeDoc && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-2xl bg-surface-900 border-l border-surface-700 h-full flex flex-col shadow-2xl animate-slide-left">
            {/* Drawer Header */}
            <div className="p-6 border-b border-surface-700 flex items-start justify-between bg-surface-850">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center text-brand-400 mt-1">
                  <FileText size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-surface-50 break-all">{activeDoc.original_name}</h2>
                  <div className="flex items-center gap-2 mt-1.5">
                    {renderDocTypeBadge(activeDoc.doc_type)}
                    {renderStatusBadge(activeDoc.status)}
                    {activeDoc.classification_confidence !== null && (
                      <span className="text-[11px] text-surface-400">
                        Confidence: {(activeDoc.classification_confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <button
                onClick={() => setActiveDoc(null)}
                className="p-1.5 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-700"
              >
                <X size={20} />
              </button>
            </div>

            {/* Sub-tabs */}
            <div className="flex items-center gap-4 px-6 pt-3 border-b border-surface-700 bg-surface-850/50">
              <button
                onClick={() => setActiveTab('fields')}
                className={`pb-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
                  activeTab === 'fields'
                    ? 'border-brand-500 text-brand-400'
                    : 'border-transparent text-surface-400 hover:text-surface-200'
                }`}
              >
                <ShieldCheck size={14} />
                Extracted Evidence
              </button>
              <button
                onClick={() => {
                  setActiveTab('chunks');
                  if (chunks.length === 0) loadChunks(activeDoc.id);
                }}
                className={`pb-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
                  activeTab === 'chunks'
                    ? 'border-brand-500 text-brand-400'
                    : 'border-transparent text-surface-400 hover:text-surface-200'
                }`}
              >
                <Layers size={14} />
                RAG Chunks
              </button>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {activeTab === 'fields' && (
                <div className="space-y-4">
                  {/* Zero-Hallucination Policy Alert */}
                  <div className="p-3.5 rounded-xl bg-brand-500/5 border border-brand-500/20 flex items-start gap-2.5">
                    <ShieldCheck size={16} className="text-brand-400 flex-shrink-0 mt-0.5" />
                    <p className="text-xs text-brand-300/80 leading-relaxed">
                      Every extracted value below includes verified page provenance and raw snippet citations. Unverified fields are strictly marked missing to prevent AI fabrication.
                    </p>
                  </div>

                  {activeDoc.error_message && (
                    <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300">
                      <strong>Processing Error:</strong> {activeDoc.error_message}
                    </div>
                  )}

                  {activeDoc.extracted_fields ? (
                    <div className="grid grid-cols-1 gap-3">
                      {Object.entries(activeDoc.extracted_fields).map(([key, field]) => {
                        const label = key.replace('_', ' ').toUpperCase();
                        const isVerified = field.status === 'verified';
                        const isInferred = field.status === 'inferred';
                        const isMissing = field.status === 'missing';

                        return (
                          <div
                            key={key}
                            className={`p-4 rounded-xl border transition-all ${
                              isVerified
                                ? 'bg-surface-800/80 border-surface-700 hover:border-brand-500/40'
                                : isInferred
                                ? 'bg-surface-800/50 border-surface-700/80'
                                : 'bg-surface-850/40 border-surface-800 opacity-60'
                            }`}
                          >
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-[11px] font-bold tracking-wider text-surface-400 uppercase">
                                {label}
                              </span>
                              <div className="flex items-center gap-2">
                                {isVerified && (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                                    <Check size={10} /> Verified
                                  </span>
                                )}
                                {isInferred && (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                    Inferred
                                  </span>
                                )}
                                {isMissing && (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface-600/20 text-surface-400">
                                    Missing
                                  </span>
                                )}
                                {field.confidence > 0 && (
                                  <span className="text-[10px] text-surface-400 font-mono">
                                    {(field.confidence * 100).toFixed(0)}%
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Value display */}
                            <div className="flex items-baseline justify-between gap-2">
                              <div className="text-base font-semibold text-surface-100">
                                {field.value !== null && field.value !== undefined ? (
                                  key.includes('amount') ? (
                                    `$${Number(field.value).toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                                  ) : (
                                    String(field.value)
                                  )
                                ) : (
                                  <span className="text-surface-500 font-normal italic">Not detected in text</span>
                                )}
                              </div>
                              {field.value && (
                                <button
                                  onClick={() => copyToClipboard(String(field.value), key)}
                                  className="text-surface-400 hover:text-surface-200 transition-colors"
                                  title="Copy value"
                                >
                                  {copiedField === key ? (
                                    <Check size={14} className="text-emerald-400" />
                                  ) : (
                                    <Copy size={14} />
                                  )}
                                </button>
                              )}
                            </div>

                            {/* Citation citation snippet */}
                            {field.source_text && (
                              <div className="mt-3 pt-2.5 border-t border-surface-700/60 flex items-start gap-2 text-xs text-surface-400 bg-surface-900/40 p-2 rounded-lg">
                                <Quote size={12} className="text-brand-400 flex-shrink-0 mt-0.5" />
                                <div className="space-y-1">
                                  <div className="text-[11px] text-brand-300/80 font-medium">
                                    Citation {field.page ? `• Page ${field.page}` : ''}
                                  </div>
                                  <div className="text-surface-300 font-mono text-[11px] leading-relaxed break-all">
                                    "{field.source_text}"
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="py-12 text-center text-surface-400">
                      {activeDoc.status === 'PROCESSING' ? (
                        <div className="space-y-2">
                          <RefreshCw size={24} className="animate-spin mx-auto text-brand-400" />
                          <p>AI extraction in progress. Please wait a moment...</p>
                        </div>
                      ) : (
                        <p>No extracted fields available.</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'chunks' && (
                <div className="space-y-3">
                  <div className="p-3 rounded-xl bg-purple-500/5 border border-purple-500/20 text-xs text-purple-300">
                    Prepared text chunks with page tracking for Phase 3 vector semantic search & question answering.
                  </div>

                  {loadingChunks ? (
                    <div className="py-12 text-center text-surface-400">
                      <RefreshCw size={24} className="animate-spin mx-auto text-brand-400" />
                      Loading chunks...
                    </div>
                  ) : chunks.length === 0 ? (
                    <div className="py-12 text-center text-surface-400">
                      No chunks indexed for this document.
                    </div>
                  ) : (
                    chunks.map((chk) => (
                      <div
                        key={chk.id || chk.chunk_index}
                        className="p-3.5 rounded-xl bg-surface-800 border border-surface-700 space-y-1.5"
                      >
                        <div className="flex items-center justify-between text-[11px] text-surface-400">
                          <span className="font-semibold text-brand-400">Chunk #{chk.chunk_index + 1}</span>
                          <span>Page {chk.page_number || '1'}</span>
                        </div>
                        <p className="text-xs text-surface-300 font-mono bg-surface-900/60 p-2.5 rounded-lg whitespace-pre-wrap leading-relaxed">
                          {chk.chunk_text}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deletingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="card max-w-md w-full bg-surface-850 border-surface-700 space-y-4">
            <div className="flex items-center gap-3 text-rose-400">
              <div className="w-10 h-10 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
                <Trash2 size={20} />
              </div>
              <div>
                <h3 className="text-base font-bold text-surface-100">Delete Document</h3>
                <p className="text-xs text-surface-400">This action cannot be undone.</p>
              </div>
            </div>

            <p className="text-sm text-surface-300">
              Are you sure you want to permanently delete this document and all associated extracted evidence and RAG chunks?
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setDeletingId(null)}
                className="btn-secondary text-xs"
                disabled={isDeleting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                className="btn-danger text-xs flex items-center gap-2"
                disabled={isDeleting}
              >
                {isDeleting && <RefreshCw size={14} className="animate-spin" />}
                Delete Document
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
