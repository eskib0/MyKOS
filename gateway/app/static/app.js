const state = {
  conversationId: localStorage.getItem("mykos-conversation") || "",
  models: [],
  allowedRoots: [],
  conversations: [],
  pendingApprovals: [],
  approvalBusy: new Set(),
  attachments: [],
  ollamaJobs: [],
  ollamaCatalog: [],
  benchmarkProfiles: [],
  benchmarkResults: {},
  benchmarkBusy: false,
  oauthProviders: [],
  oauth: {},
  oauthPollTimers: {},
  oauthPollSeq: {},
  libraryItems: [],
  libraryResults: [],
  libraryRoot: "mykos",
  libraryPath: ".",
  busy: false,
  context: null,
  activityId: "",
  activityPollTimer: null,
  activityPollInFlight: false,
  activityErrorTimer: null,
  automations: [],
  automationEvents: [],
  automationPollTimer: null,
  automationPollInFlight: false,
  managementStatus: null,
  managementPollInFlight: false,
  mediaStatus: null,
  mediaFiles: [],
  mediaPollInFlight: false,
  nodes: [],
  nodesPollInFlight: false,
  localVoiceCall: false,
  localVoiceCallId: "",
  localVoiceRecorder: null,
  localVoiceStream: null,
  localVoiceChunks: [],
  localVoiceAudio: null,
  localVoiceAudioResolver: null,
  localVoiceStopping: false,
  localVoiceAudioContext: null,
  localVoiceAnalyser: null,
  localVoiceFrame: 0,
  localVoiceNoiseFloor: 0.006,
  localVoiceSpeechSince: 0,
  localVoiceSilenceSince: 0,
  localVoiceSegmentStartedAt: 0,
  localVoiceTurnAbort: null,
  localVoiceQueue: Promise.resolve(),
  localVoiceInterrupted: false,
  callVisual: null,
  callTranscript: null,
  callEventTypes: new Set(),
  callVisualMode: "connecting",
  callStartedAt: 0,
  callTimerId: 0,
  callAudioContext: null,
  callMicAnalyser: null,
  callRemoteAnalyser: null,
  realtimeVoiceActive: false,
  realtimePeer: null,
  realtimeChannel: null,
  realtimeAudio: null,
  realtimeTranscriptIds: new Set(),
  realtimeDelegationIds: new Set(),
  geminiLiveActive: false,
  geminiLiveSocket: null,
  geminiLiveInputContext: null,
  geminiLiveInputProcessor: null,
  geminiLiveInputSource: null,
  geminiLiveInputSink: null,
  geminiLiveOutputContext: null,
  geminiLiveOutputAt: 0,
  geminiLiveOutputSources: new Set(),
  geminiLiveSetupResolve: null,
  geminiLiveSetupReject: null,
  geminiLiveSetupTimer: 0,
  geminiLiveClosing: false,
  geminiLiveTranscriptCounter: 0,
  helpLoaded: false,
  activeModelsTab: null,
  engines: null,
};

const elements = {
  messages: document.querySelector("#messages"),
  sessionActions: document.querySelector(".session-actions"),
  deleteSession: document.querySelector("#delete-session"),
  exportSession: document.querySelector("#export-session"),
  compactContext: document.querySelector("#compact-context"),
  helpCommands: document.querySelector("#help-commands"),
  helpPanel: document.querySelector("#help-panel"),
  helpClose: document.querySelector("#help-close"),
  helpList: document.querySelector("#help-list"),
  input: document.querySelector("#message-input"),
  composer: document.querySelector("#composer"),
  send: document.querySelector("#send-button"),
  model: document.querySelector("#model-select"),
  modelMeta: document.querySelector("#model-meta"),
  headerModel: document.querySelector("#header-model"),
  activityStatus: document.querySelector("#activity-status"),
  activityLabel: document.querySelector("#activity-label"),
  activityElapsed: document.querySelector("#activity-elapsed"),
  activityDetail: document.querySelector("#activity-detail"),
  sidebar: document.querySelector("#sidebar"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  chatPanel: document.querySelector(".chat-panel"),
  cortexBtn: document.querySelector("#cortex-btn"),
  openSwarmButton: document.querySelector("#open-swarm-button"),
  cortexPage: document.querySelector("#cortex-page"),
  swarmPage: document.querySelector("#swarm-page"),
  swarmTitleInput: document.querySelector("#swarm-title-input"),
  swarmTitleSave: document.querySelector("#swarm-title-save"),
  swarmLiveStats: document.querySelector("#swarm-live-stats"),
  swarmPermissionMode: document.querySelector("#swarm-permission-mode"),
  swarmTeamTemplate: document.querySelector("#swarm-team-template"),
  swarmQuickTeam: document.querySelector("#swarm-quick-team"),
  swarmSaveCortexBtn: document.querySelector("#swarm-save-cortex-btn"),
  swarmResetBtn: document.querySelector("#swarm-reset-btn"),
  swarmBack: document.querySelector("#swarm-back"),
  swarmAddForm: document.querySelector("#swarm-add-form"),
  swarmWorkerName: document.querySelector("#swarm-worker-name"),
  swarmWorkerRole: document.querySelector("#swarm-worker-role"),
  swarmWorkerModel: document.querySelector("#swarm-worker-model"),
  swarmWorkerBrief: document.querySelector("#swarm-worker-brief"),
  swarmStatusBanner: document.querySelector("#swarm-status-banner"),
  swarmRosterCount: document.querySelector("#swarm-roster-count"),
  swarmRosterList: document.querySelector("#swarm-roster-list"),
  swarmBoardHead: document.querySelector("#swarm-board-head"),
  swarmBoardFeed: document.querySelector("#swarm-board-feed"),
  swarmMentionChips: document.querySelector("#swarm-mention-chips"),
  swarmBoardForm: document.querySelector("#swarm-board-form"),
  swarmBoardInput: document.querySelector("#swarm-board-input"),
  swarmCanvas: document.querySelector("#swarm-canvas"),
  cortexRefresh: document.querySelector("#cortex-refresh"),
  cortexBack: document.querySelector("#cortex-back"),
  cortexSearch: document.querySelector("#cortex-search"),
  cortexStats: document.querySelector("#cortex-stats"),
  cortexFit: document.querySelector("#cortex-fit"),
  cortexCanvas: document.querySelector("#cortex-canvas"),
  cortexTooltip: document.querySelector("#cortex-tooltip"),
  cortexNotePane: document.querySelector("#cortex-note-pane"),
  cortexNoteTitle: document.querySelector("#cortex-note-title"),
  cortexNotePath: document.querySelector("#cortex-note-path"),
  cortexModeToggle: document.querySelector("#cortex-mode-toggle"),
  cortexNoteSave: document.querySelector("#cortex-note-save"),
  cortexNoteTags: document.querySelector("#cortex-note-tags"),
  cortexNoteStatus: document.querySelector("#cortex-note-status"),
  cortexNoteViewer: document.querySelector("#cortex-note-viewer"),
  cortexNoteEditor: document.querySelector("#cortex-note-editor"),
  cortexBacklinksCount: document.querySelector("#cortex-backlinks-count"),
  cortexBacklinksList: document.querySelector("#cortex-backlinks-list"),
  modelsPage: document.querySelector("#models-page"),
  modelsPageContent: document.querySelector("#models-page-content"),
  modelsBack: document.querySelector("#models-back"),
  permissionsPage: document.querySelector("#permissions-page"),
  permissionsPageContent: document.querySelector("#permissions-page-content"),
  permissionsBack: document.querySelector("#permissions-back"),
  automationsPage: document.querySelector("#automations-page"),
  automationsBack: document.querySelector("#automations-back"),
  automationsCount: document.querySelector("#automations-count"),
  automationsList: document.querySelector("#automations-list"),
  automationEventsList: document.querySelector("#automation-events-list"),
  automationEventsClear: document.querySelector("#automation-events-clear"),
  automationCreateForm: document.querySelector("#automation-create-form"),
  automationTitle: document.querySelector("#automation-title"),
  automationMessage: document.querySelector("#automation-message"),
  automationRunAt: document.querySelector("#automation-run-at"),
  automationRepeat: document.querySelector("#automation-repeat"),
  automationCreateStatus: document.querySelector("#automation-create-status"),
  managementPage: document.querySelector("#management-page"),
  managementRefresh: document.querySelector("#management-refresh"),
  managementChecked: document.querySelector("#management-checked"),
  managementChecks: document.querySelector("#management-checks"),
  managementDetails: document.querySelector("#management-details"),
  mediaPage: document.querySelector("#media-page"),
  mediaRefresh: document.querySelector("#media-refresh"),
  mediaChecked: document.querySelector("#media-checked"),
  mediaEngines: document.querySelector("#media-engines"),
  mediaCount: document.querySelector("#media-count"),
  mediaFiles: document.querySelector("#media-files"),
  nodesPage: document.querySelector("#nodes-page"),
  nodesRefresh: document.querySelector("#nodes-refresh"),
  nodesCount: document.querySelector("#nodes-count"),
  nodesList: document.querySelector("#nodes-list"),
  userProfileForm: document.querySelector("#user-profile-form"),
  userProfileName: document.querySelector("#user-profile-name"),
  userProfileLocation: document.querySelector("#user-profile-location"),
  userProfileRole: document.querySelector("#user-profile-role"),
  userProfileTone: document.querySelector("#user-profile-tone"),
  userProfileNotes: document.querySelector("#user-profile-notes"),
  userProfileSaveBtn: document.querySelector("#user-profile-save-btn"),
  userProfileStatus: document.querySelector("#user-profile-status"),
  userProfileRaw: document.querySelector("#user-profile-raw"),
  userProfileSaveRawBtn: document.querySelector("#user-profile-save-raw-btn"),
  userProfileTokenBadge: document.querySelector("#user-profile-token-badge"),
  userProfileReload: document.querySelector("#user-profile-reload"),
  userProfileFilePath: document.querySelector("#user-profile-file-path"),
  userProfileCharCount: document.querySelector("#user-profile-char-count"),
  headerUpdatePill: document.querySelector("#header-update-pill"),
  headerUpdateVersion: document.querySelector("#header-update-version"),
  headerUpdateLabel: document.querySelector("#header-update-label"),
  systemUpdateBadge: document.querySelector("#system-update-badge"),
  updateCurrentVer: document.querySelector("#update-current-ver"),
  updateLatestVer: document.querySelector("#update-latest-ver"),
  updateRepoName: document.querySelector("#update-repo-name"),
  updateModeName: document.querySelector("#update-mode-name"),
  updateNotesCard: document.querySelector("#update-notes-card"),
  updateReleaseTitle: document.querySelector("#update-release-title"),
  updateReleaseDate: document.querySelector("#update-release-date"),
  updateReleaseBody: document.querySelector("#update-release-body"),
  btnCheckUpdates: document.querySelector("#btn-check-updates"),
  btnApplyUpdate: document.querySelector("#btn-apply-update"),
  updateProgressBar: document.querySelector("#update-progress-bar"),
  updateStatusMsg: document.querySelector("#update-status-msg"),
  settingsPage: document.querySelector("#settings-page"),
  settingsBack: document.querySelector("#settings-back"),
  settingsNavBtn: document.querySelector("#settings-nav-btn"),
  navItems: [...document.querySelectorAll(".app-nav-item")],
  providerDirectoryList: document.querySelector("#provider-directory-list"),
  modelInventoryList: document.querySelector("#model-inventory-list"),
  modelDetail: document.querySelector("#model-detail"),
  modelsTotalCount: document.querySelector("#models-total-count"),
  modelsProviderCount: document.querySelector("#models-provider-count"),
  modelsDefaultName: document.querySelector("#models-default-name"),
  modelsConnectedCount: document.querySelector("#models-connected-count"),
  contextMeter: document.querySelector("#context-meter"),
  contextMeterLabel: document.querySelector("#context-meter-label"),
  contextMeterBar: document.querySelector("#context-meter-bar"),
  contextMeterDetail: document.querySelector("#context-meter-detail"),
  connection: document.querySelector("#connection"),
  newChat: document.querySelector("#new-chat"),
  historySection: document.querySelector("#history-section"),
  toggleConversations: document.querySelector("#toggle-conversations"),
  conversationList: document.querySelector("#conversation-list"),
  conversationCount: document.querySelector("#conversation-count"),
  privacyNote: document.querySelector("#privacy-note"),
  oauthStatus: document.querySelector("#oauth-status"),
  oauthOpenai: document.querySelector("#oauth-openai"),
  openaiApiToggle: document.querySelector("#openai-api-toggle"),
  oauthOpenaiLogout: document.querySelector("#oauth-openai-logout"),
  openaiApiKeyRow: document.querySelector("#openai-api-key-row"),
  openaiApiKey: document.querySelector("#openai-api-key"),
  openaiApiSave: document.querySelector("#openai-api-save"),
  openaiModels: document.querySelector("#openai-models"),
  oauthRefresh: document.querySelector("#oauth-refresh"),
  oauthClaude: document.querySelector("#oauth-claude"),
  oauthClaudeLogout: document.querySelector("#oauth-claude-logout"),
  oauthClaudeRefresh: document.querySelector("#oauth-claude-refresh"),
  oauthClaudeStatus: document.querySelector("#oauth-claude-status"),
  anthropicApiConnect: document.querySelector("#anthropic-api-connect"),
  anthropicApiKeyRow: document.querySelector("#anthropic-api-key-row"),
  anthropicApiKey: document.querySelector("#anthropic-api-key"),
  anthropicApiSave: document.querySelector("#anthropic-api-save"),
  anthropicApiModels: document.querySelector("#anthropic-api-models"),
  oauthOpenrouter: document.querySelector("#oauth-openrouter"),
  openrouterApiToggle: document.querySelector("#openrouter-api-toggle"),
  oauthOpenrouterLogout: document.querySelector("#oauth-openrouter-logout"),
  openrouterApiKeyRow: document.querySelector("#openrouter-api-key-row"),
  openrouterApiKey: document.querySelector("#openrouter-api-key"),
  openrouterApiSave: document.querySelector("#openrouter-api-save"),
  oauthOpenrouterRefresh: document.querySelector("#oauth-openrouter-refresh"),
  oauthOpenrouterStatus: document.querySelector("#oauth-openrouter-status"),
  oauthOpenrouterModels: document.querySelector("#oauth-openrouter-models"),
  oauthMeta: document.querySelector("#oauth-meta"),
  metaApiToggle: document.querySelector("#meta-api-toggle"),
  oauthMetaLogout: document.querySelector("#oauth-meta-logout"),
  metaApiKeyRow: document.querySelector("#meta-api-key-row"),
  metaApiKey: document.querySelector("#meta-api-key"),
  metaApiSave: document.querySelector("#meta-api-save"),
  oauthMetaRefresh: document.querySelector("#oauth-meta-refresh"),
  oauthMetaStatus: document.querySelector("#oauth-meta-status"),
  oauthMetaModels: document.querySelector("#oauth-meta-models"),
  grokRefresh: document.querySelector("#grok-refresh"),
  grokStatus: document.querySelector("#grok-status"),
  grokOauthConnect: document.querySelector("#grok-oauth-connect"),
  grokApiToggle: document.querySelector("#grok-api-toggle"),
  grokLogout: document.querySelector("#grok-logout"),
  grokKeyRow: document.querySelector("#grok-key-row"),
  grokApiKey: document.querySelector("#grok-api-key"),
  grokApiSave: document.querySelector("#grok-api-save"),
  grokModels: document.querySelector("#grok-models"),
  nvidiaApiRefresh: document.querySelector("#nvidia-api-refresh"),
  nvidiaApiConnect: document.querySelector("#nvidia-api-connect"),
  nvidiaApiLogout: document.querySelector("#nvidia-api-logout"),
  nvidiaApiKeyRow: document.querySelector("#nvidia-api-key-row"),
  nvidiaApiKey: document.querySelector("#nvidia-api-key"),
  nvidiaApiSave: document.querySelector("#nvidia-api-save"),
  nvidiaApiStatus: document.querySelector("#nvidia-api-status"),
  nvidiaApiModels: document.querySelector("#nvidia-api-models"),
  kimiApiRefresh: document.querySelector("#kimi-api-refresh"),
  kimiApiConnect: document.querySelector("#kimi-api-connect"),
  kimiApiLogout: document.querySelector("#kimi-api-logout"),
  kimiApiKeyRow: document.querySelector("#kimi-api-key-row"),
  kimiApiKey: document.querySelector("#kimi-api-key"),
  kimiApiSave: document.querySelector("#kimi-api-save"),
  kimiApiStatus: document.querySelector("#kimi-api-status"),
  kimiApiModels: document.querySelector("#kimi-api-models"),
  geminiApiRefresh: document.querySelector("#gemini-api-refresh"),
  geminiApiConnect: document.querySelector("#gemini-api-connect"),
  geminiApiLogout: document.querySelector("#gemini-api-logout"),
  geminiApiKeyRow: document.querySelector("#gemini-api-key-row"),
  geminiApiKey: document.querySelector("#gemini-api-key"),
  geminiApiSave: document.querySelector("#gemini-api-save"),
  geminiApiStatus: document.querySelector("#gemini-api-status"),
  geminiApiModels: document.querySelector("#gemini-api-models"),
  mistralApiRefresh: document.querySelector("#mistral-api-refresh"),
  mistralApiConnect: document.querySelector("#mistral-api-connect"),
  mistralApiVibe: document.querySelector("#mistral-api-vibe"),
  mistralApiLogout: document.querySelector("#mistral-api-logout"),
  mistralApiKeyRow: document.querySelector("#mistral-api-key-row"),
  mistralApiKey: document.querySelector("#mistral-api-key"),
  mistralApiSave: document.querySelector("#mistral-api-save"),
  mistralApiStatus: document.querySelector("#mistral-api-status"),
  mistralApiModels: document.querySelector("#mistral-api-models"),
  antigravityCliRefresh: document.querySelector("#antigravity-cli-refresh"),
  antigravityCliToggle: document.querySelector("#antigravity-cli-toggle"),
  antigravityCliStatus: document.querySelector("#antigravity-cli-status"),
  antigravityCliModels: document.querySelector("#antigravity-cli-models"),
  qwenCliRefresh: document.querySelector("#qwen-cli-refresh"),
  qwenCliToggle: document.querySelector("#qwen-cli-toggle"),
  qwenCliStatus: document.querySelector("#qwen-cli-status"),
  qwenCliModels: document.querySelector("#qwen-cli-models"),
  toolsMeta: document.querySelector("#tools-meta"),
  memoryMeta: document.querySelector("#memory-meta"),
  modelTuningToggle: document.querySelector("#model-tuning-toggle"),
  modelTuning: document.querySelector("#model-tuning"),
  modelEffort: document.querySelector("#model-effort"),
  modelSpeed: document.querySelector("#model-speed"),
  modelCreativity: document.querySelector("#model-creativity"),
  modelTuningMeta: document.querySelector("#model-tuning-meta"),
  benchmarkToggle: document.querySelector("#benchmark-toggle"),
  benchmarkManager: document.querySelector("#benchmark-manager"),
  benchmarkCurrent: document.querySelector("#benchmark-current"),
  benchmarkAll: document.querySelector("#benchmark-all"),
  benchmarkIncludeFull: document.querySelector("#benchmark-include-full"),
  benchmarkStatus: document.querySelector("#benchmark-status"),
  benchmarkList: document.querySelector("#benchmark-list"),
  permissionsToggle: document.querySelector("#permissions-toggle"),
  permissionsManager: document.querySelector("#permissions-manager"),
  voiceModeToggle: document.querySelector("#voice-mode-toggle"),
  voiceModeContent: document.querySelector("#voice-mode-content"),
  voiceModeStatus: document.querySelector("#voice-mode-status"),
  voiceModeDetail: document.querySelector("#voice-mode-detail"),
  voiceModeLocalButton: document.querySelector("#voice-mode-local"),
  voiceModeCloudButton: document.querySelector("#voice-mode-cloud"),
  voiceModeGeminiButton: document.querySelector("#voice-mode-gemini"),
  permissionsStatus: document.querySelector("#permissions-status"),
  permissionsList: document.querySelector("#permissions-list"),
  auditList: document.querySelector("#audit-list"),
  approvalsPanel: document.querySelector("#approvals-panel"),
  ollamaToggle: document.querySelector("#ollama-toggle"),
  ollamaManager: document.querySelector("#ollama-manager"),
  ollamaInstalledList: document.querySelector("#ollama-installed-list"),
  ollamaCatalogForm: document.querySelector("#ollama-catalog-form"),
  ollamaCatalogQuery: document.querySelector("#ollama-catalog-query"),
  ollamaCatalogStatus: document.querySelector("#ollama-catalog-status"),
  ollamaCatalogList: document.querySelector("#ollama-catalog-list"),
  ollamaJobList: document.querySelector("#ollama-job-list"),
  dropzone: document.querySelector("#dropzone"),
  fileInput: document.querySelector("#file-input"),
  attachmentList: document.querySelector("#attachment-list"),
  voiceInputButton: document.querySelector("#voice-input-button"),
  voiceInputLabel: document.querySelector("#voice-input-label"),
  voiceHangupButton: document.querySelector("#voice-hangup-button"),
  voiceCallStage: document.querySelector("#voice-call-stage"),
  voiceCallStatus: document.querySelector("#voice-call-status"),
  voiceCallDetail: document.querySelector("#voice-call-detail"),
  voiceCallCanvas: document.querySelector("#voice-call-canvas"),
  voiceCallTimer: document.querySelector("#voice-call-timer"),
  voiceTranscriptList: document.querySelector("#voice-transcript-list"),
  voiceTranscriptToggle: document.querySelector("#voice-transcript-toggle"),
  voiceStageHangupButton: document.querySelector("#voice-stage-hangup-button"),
  voiceMinimizeButton: document.querySelector("#voice-minimize-button"),
  voiceCallCompactBar: document.querySelector("#voice-call-compact-bar"),
  voiceCompactDot: document.querySelector("#voice-compact-dot"),
  voiceCompactTimer: document.querySelector("#voice-compact-timer"),
  voiceCompactExpandButton: document.querySelector("#voice-compact-expand-button"),
  voiceCompactHangupButton: document.querySelector("#voice-compact-hangup-button"),
  voiceModeButton: document.querySelector("#voice-mode-button"),
  libraryToggle: document.querySelector("#library-toggle"),
  libraryManager: document.querySelector("#library-manager"),
  libraryRoot: document.querySelector("#library-root"),
  libraryPath: document.querySelector("#library-path"),
  libraryOpenPath: document.querySelector("#library-open-path"),
  librarySearchForm: document.querySelector("#library-search-form"),
  librarySearchQuery: document.querySelector("#library-search-query"),
  libraryStatus: document.querySelector("#library-status"),
  libraryList: document.querySelector("#library-list"),
  libraryPreview: document.querySelector("#library-preview"),
  rightSidebar: document.querySelector("#right-sidebar"),
  rightSidebarToggle: document.querySelector("#right-sidebar-toggle"),
  rightSidebarClose: document.querySelector("#right-sidebar-close"),
  terminalScreen: document.querySelector("#terminal-screen"),
  terminalForm: document.querySelector("#terminal-form"),
  terminalInput: document.querySelector("#terminal-input"),
  terminalCwdBadge: document.querySelector("#terminal-cwd-badge"),
  terminalClearBtn: document.querySelector("#terminal-clear-btn"),
};

function formatBytes(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function setConnection(ok, text) {
  elements.connection.className = `connection ${ok ? "ok" : "error"}`;
  elements.connection.querySelector("span:last-child").textContent = text;
}

function selectedModel() {
  return elements.model.value || (state.models[0] && state.models[0].name) || "";
}

function updateModelMeta() {
  const model = state.models.find((item) => item.name === selectedModel());
  elements.headerModel.textContent = model ? (model.label || model.name) : "Sin modelo";
  elements.modelMeta.textContent = model
    ? [model.provider_label || (model.remote ? "remoto" : "local"), model.auth_status, model.parameter_size, model.quantization, formatBytes(model.size)].filter(Boolean).join(" · ")
    : "Instala un modelo local o inicia la sesión OAuth de Claude.";
  elements.privacyNote.textContent = model
    ? model.provider === "anthropic_oauth"
      ? "Claude se ejecuta a través de Claude Code usando tu sesión OAuth de claude.ai; no se guarda ninguna API key en MyKOS."
      : model.provider === "anthropic_api"
      ? "Este modelo se conecta directamente a Anthropic Messages API usando tu clave API personal cifrada en MyKOS."
      : model.provider === "openai_api"
      ? "Este modelo se conecta directamente a OpenAI API (/v1/chat/completions) usando tu clave API personal cifrada en MyKOS."
      : model.provider === "openai_codex_oauth"
      ? "Este modelo se conecta mediante Codex usando tu sesión OpenAI OAuth propia de MyKOS."
      : model.remote
      ? (model.provider === "qwen_cli"
        ? "Este modelo se conecta vía Qwen Code CLI y razona en la nube (Qwen Plus / OAuth / DashScope)."
        : model.provider === "antigravity" || model.provider === "antigravity_cli"
        ? "Este modelo se conecta vía Antigravity CLI y razona en la nube de Google."
        : "Este modelo puede enviar las peticiones fuera de este equipo a servidores en la nube.")
      : model.provider === "strata"
      ? "Este modelo se ejecuta localmente mediante Strata con GPU CUDA."
      : (model.provider === "llama_cpp" || model.provider === "llamacpp")
      ? "Este modelo se ejecuta localmente mediante llama.cpp con CUDA."
      : "Este modelo se ejecuta localmente mediante Ollama."
    : "";
  elements.privacyNote.className = `privacy-note${model && model.remote ? " remote" : ""}`;
}

function makeId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `activity-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const remaining = String(total % 60).padStart(2, "0");
  return `${minutes}:${remaining}`;
}

function renderActivity(data = {}) {
  const active = Boolean(data.active);
  const status = active ? String(data.status || "working") : String(data.status || "idle");
  const className = active
    ? (status === "waiting" ? "waiting" : status === "error" ? "error" : "working")
    : status === "error" ? "error" : "idle";
  elements.activityStatus.className = `activity-status ${className}`;
  elements.activityLabel.textContent = active
    ? String(data.label || (status === "waiting" ? "Esperando…" : "Trabajando…"))
    : status === "error" ? "Error" : "Listo";
  elements.activityElapsed.textContent = active && Number.isFinite(Number(data.elapsed_seconds))
    ? ` · ${formatElapsed(data.elapsed_seconds)}`
    : "";
  elements.activityDetail.textContent = active
    ? String(data.detail || `${data.model_label || "Modelo"} · ${data.location || ""}`)
    : String(data.detail || "Esperando una petición.");
}

function beginActivity() {
  state.activityId = makeId();
  if (state.activityErrorTimer) window.clearTimeout(state.activityErrorTimer);
  renderActivity({ active: true, status: "working", label: "Conectando…", detail: "Comprobando el estado del modelo." });
  if (state.activityPollTimer) window.clearInterval(state.activityPollTimer);
  pollActivity();
  state.activityPollTimer = window.setInterval(pollActivity, 700);
  return state.activityId;
}

function endActivity(errorMessage = "", waitingForApproval = false) {
  if (state.activityPollTimer) window.clearInterval(state.activityPollTimer);
  state.activityPollTimer = null;
  state.activityPollInFlight = false;
  if (errorMessage) {
    renderActivity({ status: "error", detail: errorMessage });
    state.activityErrorTimer = window.setTimeout(() => renderActivity(), 5000);
  } else if (waitingForApproval) {
    renderActivity({ active: true, status: "waiting", label: "Esperando tu aprobación…", detail: "Revisa la acción pendiente en el panel." });
  } else {
    renderActivity();
  }
  state.activityId = "";
}

async function pollActivity() {
  if (!state.activityId || state.activityPollInFlight) return;
  const activityId = state.activityId;
  state.activityPollInFlight = true;
  try {
    const params = new URLSearchParams({
      activity_id: activityId,
      conversation_id: state.conversationId,
    });
    const response = await fetch(`/api/activity?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (state.activityId !== activityId) return;
    if (data.active) renderActivity(data);
    else if (state.busy) renderActivity({ active: true, status: "working", label: "Esperando respuesta…", detail: "El servidor está terminando la petición." });
  } catch (_error) {
    if (state.activityId === activityId && state.busy) {
      renderActivity({ active: true, status: "error", label: "Conexión perdida", detail: "El servidor no responde al indicador de actividad." });
    }
  } finally {
    state.activityPollInFlight = false;
  }
}

function mountModelsPage() {
  const selectorContainer = document.querySelector(".models-selector-container");
  const tuningTab = document.querySelector("#models-tab-tuning");
  const benchmarkTab = document.querySelector("#models-tab-benchmark");
  const libraryTab = document.querySelector("#models-tab-library");
  const ollamaTab = document.querySelector("#models-tab-ollama");
  const cloudProvidersContainer = document.querySelector("#cloud-providers-container");

  // 1. Selector de modelo principal
  const modelSection = elements.model?.closest(".panel-section");
  if (modelSection && selectorContainer) {
    selectorContainer.appendChild(modelSection);
  }

  // 2. Pestaña: Ajuste de modelo
  const tuningSection = document.querySelector(".model-tuning");
  if (tuningSection && tuningTab) {
    tuningTab.appendChild(tuningSection);
    if (elements.modelTuning) elements.modelTuning.hidden = false;
  }

  // 3. Pestaña: Rendimiento
  const benchmarkSection = document.querySelector(".benchmark-manager");
  if (benchmarkSection && benchmarkTab) {
    benchmarkTab.appendChild(benchmarkSection);
    if (elements.benchmarkManager) elements.benchmarkManager.hidden = false;
  }

  // 4. Pestaña: Biblioteca
  const librarySection = document.querySelector(".library-manager");
  if (librarySection && libraryTab) {
    libraryTab.appendChild(librarySection);
    if (elements.libraryManager) elements.libraryManager.hidden = false;
  }

  // 5. Pestaña: Gestión Ollama
  const ollamaSection = document.querySelector(".ollama-manager");
  if (ollamaSection && ollamaTab) {
    ollamaTab.appendChild(ollamaSection);
    if (elements.ollamaManager) elements.ollamaManager.hidden = false;
  }

  // 6. Proveedores en la nube (OAuth, APIs y asistentes CLI remotos)
  if (cloudProvidersContainer) {
    const cloudPanels = [
      document.querySelector(".openai-oauth-card"),
      document.querySelector(".claude-oauth-card"),
      document.querySelector(".openrouter-oauth-card"),
      document.querySelector(".meta-oauth-card"),
      document.querySelector(".grok-card"),
      document.querySelector(".nvidia-api-card"),
      document.querySelector(".kimi-api-card"),
      document.querySelector(".gemini-api-card"),
      document.querySelector(".mistral-api-card"),
      document.querySelector(".antigravity-cli-card"),
      document.querySelector(".qwen-cli-card"),
      document.querySelector(".oauth-new-connection"),
      ...document.querySelectorAll(".oauth-manager"),
      ...document.querySelectorAll(".provider-manager"),
    ].filter(Boolean);

    for (const panel of new Set(cloudPanels)) {
      cloudProvidersContainer.appendChild(panel);
    }
  }
}

function mountPermissionsPage() {
  const panel = document.querySelector(".permissions-manager");
  if (panel) elements.permissionsPageContent.appendChild(panel);
}

function formatAutomationDate(value) {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  } catch (_error) {
    return String(value);
  }
}

function renderAutomations() {
  elements.automationsCount.textContent = String(state.automations.length);
  elements.automationsList.replaceChildren();
  if (!state.automations.length) {
    const empty = document.createElement("div");
    empty.className = "automation-empty";
    empty.textContent = "No hay recordatorios programados. Puedes pedir uno en el chat.";
    elements.automationsList.appendChild(empty);
  }
  for (const item of state.automations) {
    const card = document.createElement("article");
    card.className = "automation-card";
    const title = document.createElement("strong");
    title.textContent = item.title || "Sin título";
    const message = document.createElement("p");
    message.textContent = item.message || "Sin mensaje adicional.";
    const meta = document.createElement("div");
    meta.className = "automation-meta";
    const repeat = item.repeat_minutes ? ` · Repite cada ${item.repeat_minutes} min` : " · Una vez";
    meta.textContent = `${item.enabled ? "Programado" : "Completado"} · ${formatAutomationDate(item.run_at)}${repeat}`;
    const deleteButton = document.createElement("button");
    deleteButton.className = "text-button danger-text-button automation-delete";
    deleteButton.type = "button";
    deleteButton.textContent = "Eliminar";
    deleteButton.addEventListener("click", () => requestDeleteAutomation(item.id, item.title));
    card.append(title, message, meta, deleteButton);
    elements.automationsList.appendChild(card);
  }

  elements.automationEventsList.replaceChildren();
  if (!state.automationEvents.length) {
    const empty = document.createElement("div");
    empty.className = "automation-empty";
    empty.textContent = "Todavía no se ha activado ningún recordatorio.";
    elements.automationEventsList.appendChild(empty);
  }
  for (const item of [...state.automationEvents].reverse()) {
    const card = document.createElement("article");
    card.className = "automation-event";
    const title = document.createElement("strong");
    title.textContent = item.title || "Recordatorio";
    const message = document.createElement("p");
    message.textContent = item.message || "";
    const meta = document.createElement("div");
    meta.className = "automation-meta";
    meta.textContent = formatAutomationDate(item.fired_at);
    card.append(title, message, meta);
    elements.automationEventsList.appendChild(card);
  }
}

async function loadAutomations() {
  if (state.automationPollInFlight) return;
  state.automationPollInFlight = true;
  try {
    const data = await api("/api/automations?limit=50");
    state.automations = Array.isArray(data.automations) ? data.automations : [];
    state.automationEvents = Array.isArray(data.events) ? data.events : [];
    renderAutomations();
  } catch (_error) {
    // El chat sigue funcionando aunque el panel de recordatorios no responda.
  } finally {
    state.automationPollInFlight = false;
  }
}

function showAutomationCreateStatus(message, isError) {
  elements.automationCreateStatus.hidden = !message;
  elements.automationCreateStatus.textContent = message || "";
  elements.automationCreateStatus.classList.toggle("error-text", Boolean(isError));
}

async function submitAutomationCreate(event) {
  event.preventDefault();
  const title = elements.automationTitle.value.trim();
  const runAtLocal = elements.automationRunAt.value;
  if (!title || !runAtLocal) return;
  const message = elements.automationMessage.value.trim();
  const repeatMinutes = Number(elements.automationRepeat.value) || 0;
  // El input datetime-local no lleva zona horaria: Date lo interpreta en la hora local del navegador,
  // y toISOString() ya lo pasa a UTC con el offset correcto para que automations.py lo acepte.
  const runAtIso = new Date(runAtLocal).toISOString();
  showAutomationCreateStatus("Preparando aprobación…", false);
  try {
    const data = await api("/api/automations/create-request", {
      method: "POST",
      body: JSON.stringify({
        title,
        message,
        run_at: runAtIso,
        repeat_minutes: repeatMinutes,
        conversation_id: state.conversationId || "",
      }),
    });
    if (data.executed) {
      showAutomationCreateStatus("Recordatorio creado.", false);
      elements.automationCreateForm.reset();
      await loadAutomations();
    } else {
      showAutomationCreateStatus("Aprueba la creación en el panel de aprobaciones para confirmarla.", false);
      elements.automationCreateForm.reset();
    }
    await loadApprovals();
  } catch (error) {
    showAutomationCreateStatus(error.message, true);
  }
}

async function clearAutomationEvents() {
  try {
    await api("/api/automations/clear-events", { method: "POST", body: JSON.stringify({}) });
    state.automationEvents = [];
    renderAutomations();
  } catch (error) {
    addBubble("assistant", `No se pudo vaciar el historial de eventos: ${error.message}`, true);
  }
}

async function requestDeleteAutomation(automationId, title) {
  if (!automationId) return;
  try {
    const data = await api("/api/automations/delete-request", {
      method: "POST",
      body: JSON.stringify({ id: automationId, conversation_id: state.conversationId || "" }),
    });
    if (data.executed) {
      await loadAutomations();
    }
    await loadApprovals();
  } catch (error) {
    addBubble("assistant", `No se pudo pedir borrar «${title || automationId}»: ${error.message}`, true);
  }
}

function renderManagement() {
  const data = state.managementStatus;
  if (!data) return;
  elements.managementChecked.textContent = formatAutomationDate(data.checked_at);
  elements.managementChecks.replaceChildren();
  for (const item of data.checks || []) {
    const row = document.createElement("div");
    row.className = "management-check";
    const dot = document.createElement("span");
    dot.className = `management-check-dot ${item.status || ""}`;
    dot.setAttribute("aria-hidden", "true");
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.label || item.id || "Componente";
    const detail = document.createElement("span");
    detail.textContent = item.detail || item.status || "";
    body.append(title, detail);
    row.append(dot, body);
    elements.managementChecks.appendChild(row);
  }
  const details = [
    ["Aplicación", data.application],
    ["PID", data.process?.pid],
    ["Python", data.process?.python],
    ["Workspace", data.paths?.workspace],
    ["Conversaciones", data.counts?.conversations],
    ["Recordatorios", data.counts?.automations],
    ["Eventos", data.counts?.automation_events],
    ["Trabajos de subagente", data.counts?.subagent_jobs],
    ["Espacio libre", formatBytes(data.disk?.free_bytes || 0)],
  ];
  elements.managementDetails.replaceChildren();
  for (const [label, value] of details) {
    const row = document.createElement("div");
    row.className = "management-detail-row";
    const left = document.createElement("span");
    left.textContent = label;
    const right = document.createElement("span");
    right.textContent = value == null ? "—" : String(value);
    row.append(left, right);
    elements.managementDetails.appendChild(row);
  }
}

async function loadManagement() {
  if (state.managementPollInFlight) return;
  state.managementPollInFlight = true;
  try {
    state.managementStatus = await api("/api/management");
    renderManagement();
  } catch (_error) {
    elements.managementChecked.textContent = "No disponible";
  } finally {
    state.managementPollInFlight = false;
  }
}

function renderMedia() {
  const status = state.mediaStatus;
  if (!status) return;
  elements.mediaChecked.textContent = new Date().toLocaleTimeString("es-ES", {hour: "2-digit", minute: "2-digit"});
  const engines = status.engines || {};
  elements.mediaEngines.replaceChildren();
  for (const [key, item] of Object.entries(engines)) {
    const row = document.createElement("div");
    row.className = "media-engine";
    const label = document.createElement("strong");
    label.textContent = key === "text_to_speech" ? "Voz local" : key === "transcription_cli" ? "Transcripción" : key === "image_reading" ? "Lectura de imágenes" : key.toUpperCase();
    const detail = document.createElement("span");
    detail.textContent = key === "transcription_cli" && item.available && !item.model_available
      ? `CLI disponible · falta modelo ${item.model || "local"}`
      : item.available ? `Disponible${item.engine ? ` · ${item.engine}` : ""}` : "No detectado";
    row.append(label, detail);
    elements.mediaEngines.appendChild(row);
  }
  elements.mediaCount.textContent = String(state.mediaFiles.length);
  elements.mediaFiles.replaceChildren();
  if (!state.mediaFiles.length) {
    const empty = document.createElement("div");
    empty.className = "automation-empty";
    empty.textContent = "Todavía no hay archivos multimedia generados.";
    elements.mediaFiles.appendChild(empty);
  }
  for (const item of state.mediaFiles) {
    const row = document.createElement("div");
    row.className = "media-file";
    const name = document.createElement("strong");
    name.textContent = item.name || "Archivo";
    const detail = document.createElement("span");
    detail.textContent = `${formatBytes(item.bytes || 0)} · ${item.path || "data/media"}`;
    row.append(name, detail);
    elements.mediaFiles.appendChild(row);
  }
}

async function loadMedia() {
  if (state.mediaPollInFlight) return;
  state.mediaPollInFlight = true;
  try {
    const data = await api("/api/media?limit=50");
    state.mediaStatus = data.status || null;
    state.mediaFiles = Array.isArray(data.library) ? data.library : [];
    renderMedia();
  } catch (_error) {
    elements.mediaChecked.textContent = "No disponible";
  } finally {
    state.mediaPollInFlight = false;
  }
}

function renderNodes() {
  elements.nodesCount.textContent = String(state.nodes.length);
  elements.nodesList.replaceChildren();
  if (!state.nodes.length) {
    const empty = document.createElement("div");
    empty.className = "automation-empty";
    empty.textContent = "No hay nodos registrados.";
    elements.nodesList.appendChild(empty);
    return;
  }
  for (const node of state.nodes) {
    const card = document.createElement("article");
    card.className = "node-card";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = node.name || node.id || "Nodo";
    const capabilities = Array.isArray(node.capabilities) ? node.capabilities.join(", ") : "";
    const detail = document.createElement("span");
    detail.textContent = `${node.kind || "node"}${capabilities ? ` · ${capabilities}` : ""}${node.local ? " · este PC" : ""}`;
    body.append(title, detail);
    const status = document.createElement("span");
    status.className = `node-status ${node.status || ""}`;
    status.textContent = node.status || "desconocido";
    card.append(body, status);
    elements.nodesList.appendChild(card);
  }
}

async function loadNodes() {
  if (state.nodesPollInFlight) return;
  state.nodesPollInFlight = true;
  try {
    const data = await api("/api/nodes");
    state.nodes = Array.isArray(data.nodes) ? data.nodes : [];
    renderNodes();
  } catch (_error) {
    elements.nodesList.replaceChildren();
    const failure = document.createElement("div");
    failure.className = "error-text";
    failure.textContent = "No se pudo consultar la red local de MyKOS.";
    elements.nodesList.appendChild(failure);
  } finally {
    state.nodesPollInFlight = false;
  }
}

function setPage(page) {
  const cortex = page === "cortex";
  const swarm = page === "swarm";
  const models = page === "models";
  const permissions = page === "permissions";
  const automations = page === "automations";
  const isSettings = page === "settings" || page === "voice" || page === "management" || page === "media" || page === "nodes";
  const configPage = cortex || swarm || models || permissions || automations || isSettings;
  elements.chatPanel.classList.toggle("models-active", configPage);
  if (elements.cortexPage) elements.cortexPage.hidden = !cortex;
  if (elements.swarmPage) elements.swarmPage.hidden = !swarm;
  elements.modelsPage.hidden = !models;
  elements.permissionsPage.hidden = !permissions;
  elements.automationsPage.hidden = !automations;
  if (elements.settingsPage) elements.settingsPage.hidden = !isSettings;
  if (elements.cortexBtn) {
    elements.cortexBtn.classList.toggle("active", cortex);
    if (cortex) elements.cortexBtn.setAttribute("aria-current", "page");
    else elements.cortexBtn.removeAttribute("aria-current");
  }
  if (elements.openSwarmButton) {
    elements.openSwarmButton.classList.toggle("active", swarm);
    if (swarm) elements.openSwarmButton.setAttribute("aria-current", "page");
    else elements.openSwarmButton.removeAttribute("aria-current");
  }
  for (const item of elements.navItems) {
    const active = item.dataset.page === page;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  if (elements.settingsNavBtn) {
    elements.settingsNavBtn.classList.toggle("active", isSettings);
    if (isSettings) elements.settingsNavBtn.setAttribute("aria-current", "page");
    else elements.settingsNavBtn.removeAttribute("aria-current");
  }
  if (cortex) {
    openCortexPage();
    return;
  }
  stopCortexLoop();
  if (swarm) {
    openSwarmPage();
    return;
  }
  if (models) {
    setModelsTab(state.activeModelsTab || null);
  } else if (permissions) {
    elements.permissionsManager.hidden = false;
    elements.permissionsToggle.textContent = "Cerrar";
    elements.permissionsToggle.setAttribute("aria-expanded", "true");
    loadPermissions();
  } else if (automations) {
    loadAutomations();
  } else if (isSettings) {
    const targetSubtab = (page === "voice" || page === "management" || page === "media" || page === "nodes") ? page : (state.activeSettingsTab || "appearance");
    setSettingsTab(targetSubtab);
  } else {
    elements.input.focus();
  }
}

function setSettingsTab(tabName) {
  const validTabs = ["appearance", "profile", "voice", "management", "media", "nodes"];
  const targetTab = validTabs.includes(tabName) ? tabName : "appearance";
  state.activeSettingsTab = targetTab;

  const tabBtns = document.querySelectorAll(".settings-tab-btn");
  for (const btn of tabBtns) {
    const active = btn.dataset.settingsTab === targetTab;
    btn.classList.toggle("active", active);
    if (active) btn.setAttribute("aria-selected", "true");
    else btn.removeAttribute("aria-selected");
  }

  const panels = {
    appearance: document.querySelector("#settings-tab-appearance"),
    profile: document.querySelector("#settings-tab-profile"),
    voice: document.querySelector("#settings-tab-voice"),
    management: document.querySelector("#management-page"),
    media: document.querySelector("#media-page"),
    nodes: document.querySelector("#nodes-page"),
  };

  for (const [key, panel] of Object.entries(panels)) {
    if (panel) {
      panel.classList.toggle("active", key === targetTab);
    }
  }

  if (targetTab === "appearance") {
    syncThemeUi();
    syncChatDimensionsUi();
  } else if (targetTab === "profile") {
    loadUserProfile();
  } else if (targetTab === "voice") {
    syncVoiceSettingsUi();
  } else if (targetTab === "management") {
    loadManagement();
  } else if (targetTab === "media") {
    loadMedia();
  } else if (targetTab === "nodes") {
    loadNodes();
  }
}

function setModelsTab(tabName) {
  const validTabs = ["tuning", "benchmark", "library", "ollama", "local-providers", "cloud-providers"];
  const targetTab = validTabs.includes(tabName) ? tabName : null;
  state.activeModelsTab = targetTab;

  const tabBtns = document.querySelectorAll(".models-tab-btn");
  for (const btn of tabBtns) {
    const active = targetTab !== null && btn.dataset.modelsTab === targetTab;
    btn.classList.toggle("active", active);
    if (active) btn.setAttribute("aria-selected", "true");
    else btn.removeAttribute("aria-selected");
  }

  const panels = {
    tuning: document.querySelector("#models-tab-tuning"),
    benchmark: document.querySelector("#models-tab-benchmark"),
    library: document.querySelector("#models-tab-library"),
    ollama: document.querySelector("#models-tab-ollama"),
    "local-providers": document.querySelector("#models-tab-local-providers"),
    "cloud-providers": document.querySelector("#models-tab-cloud-providers"),
  };

  for (const [key, panel] of Object.entries(panels)) {
    if (panel) {
      const active = targetTab !== null && key === targetTab;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    }
  }

  if (!targetTab) return;

  if (targetTab === "tuning") {
    if (elements.modelTuning) elements.modelTuning.hidden = false;
    syncModelGenerationControls();
  } else if (targetTab === "benchmark") {
    if (elements.benchmarkManager) elements.benchmarkManager.hidden = false;
    if (!state.benchmarks?.length) loadBenchmarks();
    renderBenchmarkResults();
  } else if (targetTab === "library") {
    if (elements.libraryManager) elements.libraryManager.hidden = false;
    loadLibraryRoots();
  } else if (targetTab === "ollama") {
    if (elements.ollamaManager) elements.ollamaManager.hidden = false;
    loadOllamaInstalled();
    renderOllamaInstalled();
  } else if (targetTab === "local-providers") {
    updateLocalEnginesStatus();
  } else if (targetTab === "cloud-providers") {
    loadOAuthStatus();
  }
}

async function updateLocalEnginesStatus(forceReload = false) {
  const pilotLlama = document.querySelector("#pilot-llamacpp");
  const badgeLlama = document.querySelector("#badge-llamacpp");
  const infoLlama = document.querySelector("#model-info-llamacpp");

  const pilotOllama = document.querySelector("#pilot-ollama");
  const badgeOllama = document.querySelector("#badge-ollama");
  const infoOllama = document.querySelector("#model-info-ollama");

  const pilotStrata = document.querySelector("#pilot-strata");
  const badgeStrata = document.querySelector("#badge-strata");
  const infoStrata = document.querySelector("#model-info-strata");

  if (forceReload || !state.engines) {
    try {
      const statusData = await api("/api/status");
      if (statusData && statusData.engines) {
        state.engines = statusData.engines;
      }
      if (statusData && Array.isArray(statusData.models)) {
        state.models = statusData.models;
      }
    } catch (_e) {
      // ignore
    }
  }

  const engines = state.engines || {};

  // 1. llama.cpp 0.9 (CUDA)
  const llama = engines.llamacpp;
  const llamaModels = state.models?.filter((m) => m.provider === "llama_cpp" || m.provider === "llamacpp") || [];
  const llamaOnline = Boolean((llama && llama.online) || llamaModels.length > 0);
  const llamaLoaded = llama
    ? (llama.loaded_model || "")
    : (llamaModels.find((m) => m.status === "online")?.label || llamaModels[0]?.label || llamaModels[0]?.name || "");

  if (pilotLlama && badgeLlama && infoLlama) {
    if (llamaOnline) {
      pilotLlama.className = "engine-pilot on";
      pilotLlama.title = "Estado: ON · Aceleración CUDA en RTX 5060";
      badgeLlama.className = "engine-status-badge on";
      badgeLlama.textContent = "ON";
      infoLlama.textContent = llamaLoaded
        ? `Cargado: ${llamaLoaded}`
        : `En línea · ${llamaModels.length} modelo${llamaModels.length === 1 ? "" : "s"} disponible${llamaModels.length === 1 ? "" : "s"}`;
    } else {
      pilotLlama.className = "engine-pilot off";
      pilotLlama.title = "Estado: OFF · Servidor detenido";
      badgeLlama.className = "engine-status-badge off";
      badgeLlama.textContent = "OFF";
      infoLlama.textContent = "Servidor detenido";
    }
  }

  // 2. Ollama
  const ollama = engines.ollama;
  const ollamaModels = state.models?.filter((m) => m.provider === "ollama") || [];
  const ollamaOnline = Boolean((ollama && ollama.online) || ollamaModels.length > 0);

  if (pilotOllama && badgeOllama && infoOllama) {
    if (ollamaOnline) {
      pilotOllama.className = "engine-pilot on";
      pilotOllama.title = "Estado: ON · Servidor Ollama activo";
      badgeOllama.className = "engine-status-badge on";
      badgeOllama.textContent = "ON";
      const count = ollama?.models_count !== undefined ? ollama.models_count : ollamaModels.length;
      infoOllama.textContent = `${count} modelo${count === 1 ? "" : "s"} instalado${count === 1 ? "" : "s"}`;
    } else {
      pilotOllama.className = "engine-pilot off";
      pilotOllama.title = "Estado: OFF · Servidor detenido";
      badgeOllama.className = "engine-status-badge off";
      badgeOllama.textContent = "OFF";
      infoOllama.textContent = "Servidor detenido";
    }
  }

  // 3. Strata GPU
  const strata = engines.strata;
  const strataModels = state.models?.filter((m) => m.provider === "strata") || [];
  const strataOnline = Boolean((strata && strata.online) || strataModels.length > 0);
  const strataLoaded = strata
    ? (strata.loaded_model || "")
    : (strataModels.find((m) => m.status === "online")?.label || "");

  if (pilotStrata && badgeStrata && infoStrata) {
    if (strataOnline) {
      pilotStrata.className = "engine-pilot on";
      pilotStrata.title = "Estado: ON · Strata GPU activo";
      badgeStrata.className = "engine-status-badge on";
      badgeStrata.textContent = "ON";
      infoStrata.textContent = strataLoaded ? `Cargado: ${strataLoaded}` : "En línea";
    } else {
      pilotStrata.className = "engine-pilot off";
      pilotStrata.title = "Estado: OFF · Desconectado";
      badgeStrata.className = "engine-status-badge off";
      badgeStrata.textContent = "OFF";
      infoStrata.textContent = "Desconectado";
    }
  }
}

function initModelsTabs() {
  const tabBtns = document.querySelectorAll(".models-tab-btn");
  for (const btn of tabBtns) {
    btn.addEventListener("click", () => {
      const clickedTab = btn.dataset.modelsTab;
      if (state.activeModelsTab === clickedTab) {
        setModelsTab(null);
      } else {
        setModelsTab(clickedTab);
      }
    });
  }
  const refreshBtn = document.querySelector("#local-engines-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      updateLocalEnginesStatus(true);
    });
  }
}

function estimateTokens(text) {
  if (!text) return 0;
  return Math.ceil(text.trim().length / 3.8);
}

function updateProfilePreviewFromForm() {
  const name = elements.userProfileName?.value?.trim() || "";
  const location = elements.userProfileLocation?.value?.trim() || "";
  const role = elements.userProfileRole?.value?.trim() || "";
  const tone = elements.userProfileTone?.value || "Directo y al grano";
  const notes = elements.userProfileNotes?.value?.trim() || "";

  const lines = ["# Perfil del Usuario"];
  if (name) lines.push(`- **Nombre:** ${name}`);
  if (location) lines.push(`- **Ubicación:** ${location}`);
  if (role) lines.push(`- **Rol:** ${role}`);
  if (tone) lines.push(`- **Tono preferido:** ${tone}`);
  if (notes) {
    lines.push("- **Notas personales:**");
    for (const noteLine of notes.split("\n")) {
      const trimmed = noteLine.trim();
      if (!trimmed) continue;
      lines.push(trimmed.startsWith("-") || trimmed.startsWith("*") ? `  ${trimmed}` : `  - ${trimmed}`);
    }
  }
  const markdown = lines.join("\n") + "\n";
  if (elements.userProfileRaw) {
    elements.userProfileRaw.value = markdown;
  }
  syncProfileStats(markdown);
}

function syncProfileStats(markdownText) {
  const chars = (markdownText || "").length;
  const tokens = estimateTokens(markdownText);
  if (elements.userProfileCharCount) {
    elements.userProfileCharCount.textContent = `${chars} caracteres`;
  }
  if (elements.userProfileTokenBadge) {
    elements.userProfileTokenBadge.textContent = `~${tokens} tokens`;
    elements.userProfileTokenBadge.className = tokens > 200 ? "settings-badge-alert" : "settings-badge-ok";
  }
}

async function loadUserProfile() {
  if (!elements.userProfileForm) return;
  try {
    const data = await api("/api/user-profile");
    if (elements.userProfileName) elements.userProfileName.value = data.name || "";
    if (elements.userProfileLocation) elements.userProfileLocation.value = data.location || "";
    if (elements.userProfileRole) elements.userProfileRole.value = data.role || "";
    if (elements.userProfileTone) {
      const matched = [...elements.userProfileTone.options].some((opt) => opt.value === data.tone);
      elements.userProfileTone.value = matched ? data.tone : (data.tone ? "Personalizado" : "Directo y al grano");
    }
    if (elements.userProfileNotes) elements.userProfileNotes.value = data.notes || "";
    if (elements.userProfileRaw) elements.userProfileRaw.value = data.raw_markdown || "";
    if (elements.userProfileFilePath && data.file) {
      elements.userProfileFilePath.textContent = data.file;
    }
    syncProfileStats(data.raw_markdown || "");
  } catch (_err) {
    if (elements.userProfileStatus) {
      elements.userProfileStatus.textContent = "Error al cargar perfil.";
      elements.userProfileStatus.className = "user-profile-status error";
    }
  }
}

async function saveUserProfile(fromRaw = false) {
  if (elements.userProfileSaveBtn) elements.userProfileSaveBtn.disabled = true;
  if (elements.userProfileSaveRawBtn) elements.userProfileSaveRawBtn.disabled = true;
  if (elements.userProfileStatus) {
    elements.userProfileStatus.textContent = "Guardando…";
    elements.userProfileStatus.className = "user-profile-status";
  }

  try {
    let payload;
    if (fromRaw) {
      payload = { raw_markdown: elements.userProfileRaw?.value || "" };
    } else {
      payload = {
        name: elements.userProfileName?.value?.trim() || "",
        location: elements.userProfileLocation?.value?.trim() || "",
        role: elements.userProfileRole?.value?.trim() || "",
        tone: elements.userProfileTone?.value || "Directo y al grano",
        notes: elements.userProfileNotes?.value?.trim() || "",
      };
    }

    const data = await api("/api/user-profile", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (data.ok) {
      if (elements.userProfileRaw) elements.userProfileRaw.value = data.raw_markdown || "";
      if (elements.userProfileName) elements.userProfileName.value = data.name || "";
      if (elements.userProfileLocation) elements.userProfileLocation.value = data.location || "";
      if (elements.userProfileRole) elements.userProfileRole.value = data.role || "";
      if (elements.userProfileNotes) elements.userProfileNotes.value = data.notes || "";
      if (elements.userProfileFilePath && data.file) {
        elements.userProfileFilePath.textContent = data.file;
      }
      syncProfileStats(data.raw_markdown || "");
      if (elements.userProfileStatus) {
        elements.userProfileStatus.textContent = "✓ Guardado en USER.md";
        elements.userProfileStatus.className = "user-profile-status ok";
        setTimeout(() => {
          if (elements.userProfileStatus && elements.userProfileStatus.textContent === "✓ Guardado en USER.md") {
            elements.userProfileStatus.textContent = "";
          }
        }, 3500);
      }
    }
  } catch (err) {
    if (elements.userProfileStatus) {
      elements.userProfileStatus.textContent = `Error: ${err.serverMessage || err.message || "No se pudo guardar"}`;
      elements.userProfileStatus.className = "user-profile-status error";
    }
  } finally {
    if (elements.userProfileSaveBtn) elements.userProfileSaveBtn.disabled = false;
    if (elements.userProfileSaveRawBtn) elements.userProfileSaveRawBtn.disabled = false;
  }
}

function initUserProfile() {
  if (!elements.userProfileForm) return;

  elements.userProfileForm.addEventListener("submit", (e) => {
    e.preventDefault();
    saveUserProfile(false);
  });

  elements.userProfileSaveRawBtn?.addEventListener("click", () => {
    saveUserProfile(true);
  });

  elements.userProfileReload?.addEventListener("click", () => {
    loadUserProfile();
  });

  const inputs = [
    elements.userProfileName,
    elements.userProfileLocation,
    elements.userProfileRole,
    elements.userProfileTone,
    elements.userProfileNotes,
  ];
  for (const input of inputs) {
    input?.addEventListener("input", () => {
      updateProfilePreviewFromForm();
    });
  }

  elements.userProfileRaw?.addEventListener("input", () => {
    syncProfileStats(elements.userProfileRaw.value);
  });
}

// ── Actualizaciones del Sistema (MyKOS Update) ──────────────────────────
async function checkSystemUpdates(force = false) {
  if (elements.btnCheckUpdates) elements.btnCheckUpdates.disabled = true;
  if (elements.updateStatusMsg) {
    elements.updateStatusMsg.textContent = "Comprobando actualizaciones en GitHub…";
    elements.updateStatusMsg.className = "update-status-msg";
  }

  try {
    const url = force ? "/api/system/updates?force=1" : "/api/system/updates";
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Error al verificar actualizaciones");

    // Rellenar datos en la UI
    if (elements.updateCurrentVer) {
      elements.updateCurrentVer.textContent = data.current_version
        ? `v${data.current_version.replace(/^v/, "")}${data.current_commit ? ` (${data.current_commit})` : ""}`
        : "v1.0.0";
    }
    if (elements.updateLatestVer) {
      elements.updateLatestVer.textContent = data.latest_version
        ? `v${data.latest_version.replace(/^v/, "")}${data.latest_commit && data.latest_commit !== data.latest_version ? ` (${data.latest_commit})` : ""}`
        : "—";
    }
    if (elements.updateRepoName && data.repository) {
      elements.updateRepoName.textContent = data.repository;
    }
    if (elements.updateModeName) {
      elements.updateModeName.textContent = data.is_git ? "Git Oficial" : "Paquete";
    }

    if (data.update_available) {
      // Píldora del header visible con aviso y piloto encendido
      if (elements.headerUpdatePill) {
        elements.headerUpdatePill.hidden = false;
        elements.headerUpdatePill.classList.remove("up-to-date");
        elements.headerUpdatePill.classList.add("has-update");
        const newVer = data.latest_version ? `v${data.latest_version.replace(/^v/, "")}` : "nueva versión";
        elements.headerUpdatePill.title = `Actualización ${newVer} disponible para MyKOS (haz clic para ir a Gestión local)`;
        if (elements.headerUpdateLabel) {
          elements.headerUpdateLabel.textContent = `Actualizar (${newVer})`;
        }
        if (elements.headerUpdateVersion) {
          elements.headerUpdateVersion.textContent = newVer;
        }
      }
      if (elements.systemUpdateBadge) {
        elements.systemUpdateBadge.textContent = "¡Nueva versión!";
        elements.systemUpdateBadge.className = "settings-badge-alert";
      }
      if (elements.btnApplyUpdate) {
        elements.btnApplyUpdate.disabled = false;
      }
      if (elements.updateNotesCard && (data.release_name || data.release_notes)) {
        elements.updateNotesCard.hidden = false;
        if (elements.updateReleaseTitle) {
          elements.updateReleaseTitle.textContent = data.release_name || "Novedades de la actualización";
        }
        if (elements.updateReleaseDate && data.published_at) {
          try {
            const d = new Date(data.published_at);
            elements.updateReleaseDate.textContent = d.toLocaleDateString("es-ES", { year: "numeric", month: "short", day: "numeric" });
          } catch {}
        }
        if (elements.updateReleaseBody) {
          elements.updateReleaseBody.textContent = data.release_notes || "(Sin notas adicionales)";
        }
      }
      if (elements.updateStatusMsg) {
        elements.updateStatusMsg.textContent = "Hay una actualización disponible lista para instalar.";
        elements.updateStatusMsg.className = "update-status-msg ok";
      }
    } else {
      // Sistema al día: botón accesible con piloto apagado (gris estático) mostrando la versión actual
      if (elements.headerUpdatePill) {
        elements.headerUpdatePill.hidden = false;
        elements.headerUpdatePill.classList.remove("has-update");
        elements.headerUpdatePill.classList.add("up-to-date");
        const curVer = data.current_version ? `v${data.current_version.replace(/^v/, "")}` : "v2.1.0";
        elements.headerUpdatePill.title = `MyKOS ${curVer} · En línea (haz clic para abrir Gestión local)`;
        if (elements.headerUpdateLabel) {
          elements.headerUpdateLabel.textContent = curVer;
        }
      }
      if (elements.systemUpdateBadge) {
        elements.systemUpdateBadge.textContent = "Al día";
        elements.systemUpdateBadge.className = "settings-badge-ok";
      }
      if (elements.btnApplyUpdate) elements.btnApplyUpdate.disabled = true;
      if (elements.updateNotesCard) elements.updateNotesCard.hidden = true;
      if (elements.updateStatusMsg) {
        elements.updateStatusMsg.textContent = "Tienes instalada la versión más reciente.";
        elements.updateStatusMsg.className = "update-status-msg";
      }
    }
  } catch (err) {
    if (elements.updateStatusMsg) {
      elements.updateStatusMsg.textContent = `No se pudo comprobar: ${err.message}`;
      elements.updateStatusMsg.className = "update-status-msg error";
    }
  } finally {
    if (elements.btnCheckUpdates) elements.btnCheckUpdates.disabled = false;
  }
}

async function applySystemUpdate() {
  if (!confirm("¿Deseas descargar e instalar la actualización ahora? MyKOS se reiniciará automáticamente.")) {
    return;
  }

  if (elements.btnApplyUpdate) elements.btnApplyUpdate.disabled = true;
  if (elements.btnCheckUpdates) elements.btnCheckUpdates.disabled = true;
  if (elements.updateProgressBar) elements.updateProgressBar.hidden = false;
  if (elements.updateStatusMsg) {
    elements.updateStatusMsg.textContent = "Descargando e instalando actualización en caliente…";
    elements.updateStatusMsg.className = "update-status-msg";
  }

  try {
    const res = await fetch("/api/system/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Fallo al aplicar la actualización");

    if (elements.updateStatusMsg) {
      elements.updateStatusMsg.textContent = "¡Actualización instalada con éxito! Reiniciando MyKOS en 3 segundos…";
      elements.updateStatusMsg.className = "update-status-msg ok";
    }

    // Esperar a que el servidor reinicie y recargar la página
    let countdown = 3;
    const timer = setInterval(() => {
      countdown -= 1;
      if (elements.updateStatusMsg && countdown > 0) {
        elements.updateStatusMsg.textContent = `Reiniciando MyKOS en ${countdown} segundos…`;
      }
      if (countdown <= 0) {
        clearInterval(timer);
        pollForRestartAndReload();
      }
    }, 1000);
  } catch (err) {
    if (elements.updateProgressBar) elements.updateProgressBar.hidden = true;
    if (elements.btnApplyUpdate) elements.btnApplyUpdate.disabled = false;
    if (elements.btnCheckUpdates) elements.btnCheckUpdates.disabled = false;
    if (elements.updateStatusMsg) {
      elements.updateStatusMsg.textContent = `Error al actualizar: ${err.message}`;
      elements.updateStatusMsg.className = "update-status-msg error";
    }
  }
}

function pollForRestartAndReload() {
  let attempts = 0;
  const poll = setInterval(async () => {
    attempts += 1;
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (res.ok) {
        clearInterval(poll);
        window.location.reload();
      }
    } catch {}
    if (attempts > 30) {
      clearInterval(poll);
      window.location.reload();
    }
  }, 1000);
}

function initSystemUpdates() {
  elements.btnCheckUpdates?.addEventListener("click", () => checkSystemUpdates(true));
  elements.btnApplyUpdate?.addEventListener("click", () => applySystemUpdate());
  elements.headerUpdatePill?.addEventListener("click", () => {
    setPage("settings");
    setSettingsTab("management");
  });

  // Comprobar actualizaciones automáticamente 2.5s después de cargar la UI
  setTimeout(() => {
    checkSystemUpdates(false);
  }, 2500);
}

function initSettingsTabs() {
  const tabBtns = document.querySelectorAll(".settings-tab-btn");
  for (const btn of tabBtns) {
    btn.addEventListener("click", () => {
      setSettingsTab(btn.dataset.settingsTab);
    });
  }
}

function applyTheme(theme) {
  const validThemes = ["default", "light", "mykos"];
  const selectedTheme = validThemes.includes(theme) ? theme : "default";
  document.documentElement.dataset.theme = selectedTheme;
  try {
    localStorage.setItem("mykos_theme", selectedTheme);
  } catch {}
  syncThemeUi();
}

function syncThemeUi() {
  const currentTheme = document.documentElement.dataset.theme || "default";
  const cards = document.querySelectorAll(".theme-option-card");
  for (const card of cards) {
    card.classList.toggle("active", card.dataset.theme === currentTheme);
  }
}

function initTheme() {
  let savedTheme = "default";
  try {
    savedTheme = localStorage.getItem("mykos_theme") || "default";
  } catch {}
  applyTheme(savedTheme);

  const cards = document.querySelectorAll(".theme-option-card");
  for (const card of cards) {
    card.addEventListener("click", () => {
      const theme = card.dataset.theme;
      applyTheme(theme);
    });
  }
}

function getChatWidth() {
  try {
    const saved = localStorage.getItem("mykos_chat_width");
    if (saved && ["760", "940", "1120", "1300"].includes(saved)) return saved;
  } catch {}
  return "940";
}

function applyChatWidth(width) {
  const valid = ["760", "940", "1120", "1300"].includes(width) ? width : "940";
  document.documentElement.style.setProperty("--chat-max-width", valid + "px");
  try {
    localStorage.setItem("mykos_chat_width", valid);
  } catch {}
  syncChatDimensionsUi();
}

function getComposerHeight() {
  try {
    const saved = localStorage.getItem("mykos_composer_height");
    if (saved && ["48", "80", "120", "165"].includes(saved)) return saved;
  } catch {}
  return "80";
}

function applyComposerHeight(height) {
  const valid = ["48", "80", "120", "165"].includes(height) ? height : "80";
  document.documentElement.style.setProperty("--composer-input-height", valid + "px");
  try {
    localStorage.setItem("mykos_composer_height", valid);
  } catch {}
  syncChatDimensionsUi();
}

function syncChatDimensionsUi() {
  const currentWidth = getChatWidth();
  const currentHeight = getComposerHeight();

  const widthBtns = document.querySelectorAll(".chat-width-btn");
  for (const btn of widthBtns) {
    btn.classList.toggle("active", btn.dataset.val === currentWidth);
  }

  const heightBtns = document.querySelectorAll(".composer-height-btn");
  for (const btn of heightBtns) {
    btn.classList.toggle("active", btn.dataset.val === currentHeight);
  }
}

function initChatDimensions() {
  const savedWidth = getChatWidth();
  const savedHeight = getComposerHeight();
  applyChatWidth(savedWidth);
  applyComposerHeight(savedHeight);

  const widthBtns = document.querySelectorAll(".chat-width-btn");
  for (const btn of widthBtns) {
    btn.addEventListener("click", () => {
      applyChatWidth(btn.dataset.val);
    });
  }

  const heightBtns = document.querySelectorAll(".composer-height-btn");
  for (const btn of heightBtns) {
    btn.addEventListener("click", () => {
      applyComposerHeight(btn.dataset.val);
    });
  }
}

function getVoiceSilenceMs() {
  try {
    const saved = localStorage.getItem("mykos_voice_silence_ms");
    if (saved) {
      const val = Number(saved);
      if (val >= 400 && val <= 3000) return val;
    }
  } catch {}
  return 900;
}

function getVoiceSensitivity() {
  try {
    const saved = localStorage.getItem("mykos_voice_sensitivity");
    if (saved && ["high", "medium", "low"].includes(saved)) return saved;
  } catch {}
  return "medium";
}

function getVoiceBargeInEnabled() {
  try {
    const saved = localStorage.getItem("mykos_voice_barge_in");
    if (saved !== null) return saved === "true";
  } catch {}
  return true;
}

function getVoicePlaybackRate() {
  try {
    const saved = localStorage.getItem("mykos_voice_speed");
    if (saved) {
      const val = Number(saved);
      if (val >= 0.75 && val <= 1.5) return val;
    }
  } catch {}
  return 1.0;
}

function syncVoiceSettingsUi() {
  const silence = String(getVoiceSilenceMs());
  const sensitivity = getVoiceSensitivity();
  const bargeIn = getVoiceBargeInEnabled();
  const speed = String(getVoicePlaybackRate());

  const silenceBtns = document.querySelectorAll(".voice-silence-btn");
  for (const btn of silenceBtns) {
    btn.classList.toggle("active", btn.dataset.val === silence);
  }

  const sensBtns = document.querySelectorAll(".voice-sensitivity-btn");
  for (const btn of sensBtns) {
    btn.classList.toggle("active", btn.dataset.val === sensitivity);
  }

  const bargeInToggle = document.querySelector("#voice-barge-in-toggle");
  const bargeInStatus = document.querySelector("#voice-barge-in-status");
  if (bargeInToggle) {
    bargeInToggle.checked = bargeIn;
  }
  if (bargeInStatus) {
    bargeInStatus.textContent = bargeIn ? "Activado" : "Desactivado";
  }

  const speedBtns = document.querySelectorAll(".voice-speed-btn");
  for (const btn of speedBtns) {
    btn.classList.toggle("active", btn.dataset.val === speed);
  }
}

function initVoiceSettings() {
  syncVoiceSettingsUi();

  const silenceBtns = document.querySelectorAll(".voice-silence-btn");
  for (const btn of silenceBtns) {
    btn.addEventListener("click", () => {
      try {
        localStorage.setItem("mykos_voice_silence_ms", btn.dataset.val);
      } catch {}
      syncVoiceSettingsUi();
    });
  }

  const sensBtns = document.querySelectorAll(".voice-sensitivity-btn");
  for (const btn of sensBtns) {
    btn.addEventListener("click", () => {
      try {
        localStorage.setItem("mykos_voice_sensitivity", btn.dataset.val);
      } catch {}
      syncVoiceSettingsUi();
    });
  }

  const bargeInToggle = document.querySelector("#voice-barge-in-toggle");
  bargeInToggle?.addEventListener("change", () => {
    try {
      localStorage.setItem("mykos_voice_barge_in", String(bargeInToggle.checked));
    } catch {}
    syncVoiceSettingsUi();
  });

  const speedBtns = document.querySelectorAll(".voice-speed-btn");
  for (const btn of speedBtns) {
    btn.addEventListener("click", () => {
      try {
        localStorage.setItem("mykos_voice_speed", btn.dataset.val);
      } catch {}
      syncVoiceSettingsUi();
    });
  }
}

function restoreSidebarState() {
  const hidden = localStorage.getItem("mykos-sidebar-hidden") === "true";
  const updateToggleButtons = (isCollapsed) => {
    document.querySelectorAll(".sidebar-toggle").forEach((btn) => {
      btn.textContent = "panel MyKOS";
      btn.title = isCollapsed ? "Mostrar panel lateral" : "Ocultar panel lateral";
      btn.setAttribute("aria-label", isCollapsed ? "Mostrar panel lateral" : "Ocultar panel lateral");
      btn.setAttribute("aria-expanded", String(!isCollapsed));
    });
  };
  const closeSidebar = () => {
    document.querySelector(".app-shell").classList.add("sidebar-collapsed");
    localStorage.setItem("mykos-sidebar-hidden", "true");
    updateToggleButtons(true);
  };
  const openSidebar = () => {
    document.querySelector(".app-shell").classList.remove("sidebar-collapsed");
    localStorage.setItem("mykos-sidebar-hidden", "false");
    updateToggleButtons(false);
  };
  document.addEventListener("click", (event) => {
    if (event.target.closest(".sidebar-toggle")) {
      const isCollapsed = document.querySelector(".app-shell").classList.contains("sidebar-collapsed");
      if (isCollapsed) openSidebar();
      else closeSidebar();
    }
  });
  document.querySelector("#sidebar-close")?.addEventListener("click", closeSidebar);
  if (hidden) {
    closeSidebar();
  } else {
    openSidebar();
  }
}

function generationStore() {
  try {
    const parsed = JSON.parse(localStorage.getItem("mykos-generation") || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function currentGeneration() {
  return {
    effort: elements.modelEffort.value || "off",
    speed: elements.modelSpeed.value || "balanced",
    creativity: elements.modelCreativity.value || "balanced",
  };
}

function saveCurrentGeneration() {
  const store = generationStore();
  if (selectedModel()) store[selectedModel()] = currentGeneration();
  localStorage.setItem("mykos-generation", JSON.stringify(store));
}

function syncModelGenerationControls() {
  const model = state.models.find((item) => item.name === selectedModel());
  const store = generationStore();
  const saved = store[selectedModel()] || {};
  elements.modelEffort.value = saved.effort || "off";
  elements.modelSpeed.value = saved.speed || "balanced";
  elements.modelCreativity.value = saved.creativity || "balanced";
  const supportsThinking = Boolean(model?.thinking_capable);
  for (const option of elements.modelEffort.options) {
    option.disabled = option.value !== "off" && !supportsThinking;
  }
  if (!supportsThinking) elements.modelEffort.value = "off";
  elements.modelTuningMeta.textContent = model
    ? supportsThinking
      ? `Este modelo admite razonamiento. Contexto máximo detectado: ${formatNumber(model.context_length)} tokens.`
      : "Este modelo no anuncia razonamiento; el esfuerzo se mantendrá desactivado."
    : "Selecciona un modelo para ajustar su respuesta.";
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number.toLocaleString("es-ES") : "automático";
}

function formatContextNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number.toLocaleString("es-ES") : "—";
}

function contextQuery() {
  const generation = currentGeneration();
  return new URLSearchParams({
    model: selectedModel(),
    effort: generation.effort,
    speed: generation.speed,
    creativity: generation.creativity,
    attachments: String(state.attachments.length),
  });
}

function renderContextMeter(info) {
  if (!info || info.error) {
    elements.contextMeter.className = "context-meter";
    elements.contextMeterLabel.textContent = "—";
    elements.contextMeterBar.style.width = "0%";
    elements.contextMeterDetail.textContent = info?.error || "Sin datos de contexto.";
    return;
  }

  const estimated = Number(info.estimated_tokens) || 0;
  const maximum = Number(info.max_tokens) || 0;
  const percent = Math.max(0, Math.min(100, Number(info.percent) || 0));
  const level = ["ok", "warning", "critical"].includes(info.level) ? info.level : "ok";
  elements.contextMeter.className = `context-meter ${level}`;
  elements.contextMeterLabel.textContent = maximum
    ? `${formatContextNumber(estimated)} / ${formatContextNumber(maximum)}`
    : "—";
  elements.contextMeterBar.style.width = `${percent}%`;

  const sourceMessages = Number(info.source_message_count) || 0;
  const available = Number(info.available_tokens) || 0;
  let detail = `${percent.toLocaleString("es-ES")} % · ${sourceMessages} mensaje${sourceMessages === 1 ? "" : "s"}`;
  if (info.compacted && Number(info.omitted_messages) > 0) {
    detail = `Protegido · ${info.omitted_messages} mensaje${info.omitted_messages === 1 ? "" : "s"} antiguo${info.omitted_messages === 1 ? "" : "s"} compactado${info.omitted_messages === 1 ? "" : "s"}`;
  } else if (info.manual_compacted && Number(info.manual_omitted_messages) > 0) {
    detail = `Compactado manualmente · ${info.manual_omitted_messages} mensaje${info.manual_omitted_messages === 1 ? "" : "s"} archivado${info.manual_omitted_messages === 1 ? "" : "s"}`;
  } else if (info.would_compact) {
    detail = `Se compactará al enviar · margen ${formatContextNumber(available)}`;
  } else if (maximum) {
    detail += ` · margen ${formatContextNumber(available)}`;
  }
  elements.contextMeterDetail.textContent = detail;
  if (elements.contextMeter) {
    elements.contextMeter.title = `Contexto: ${maximum ? `${formatContextNumber(estimated)} / ${formatContextNumber(maximum)} (${percent.toLocaleString("es-ES")}%)` : "—"} · ${detail}`;
  }
}

async function loadContextMeter() {
  if (!selectedModel()) {
    renderContextMeter({ error: "Selecciona un modelo." });
    return;
  }
  try {
    const query = contextQuery();
    if (state.conversationId) query.set("id", state.conversationId);
    const data = await api(`/api/context?${query.toString()}`);
    state.context = data.context || null;
    renderContextMeter(state.context);
  } catch (error) {
    state.context = null;
    renderContextMeter({ error: error.message });
  }
}

const fallbackBenchmarkProfiles = [
  { id: "fast", label: "Rápido", description: "Contexto corto y respuesta ágil." },
  { id: "balanced", label: "Equilibrado", description: "Punto de referencia para el uso diario." },
  { id: "deep", label: "Profundo", description: "Más contexto y razonamiento cuando el modelo lo admite." },
  { id: "full", label: "Full Session · 131K", description: "Contexto máximo configurado; puede consumir bastante memoria." },
];

function benchmarkProfiles() {
  return state.benchmarkProfiles.length ? state.benchmarkProfiles : fallbackBenchmarkProfiles;
}

function benchmarkProfile(profileId) {
  return benchmarkProfiles().find((item) => item.id === profileId) || { id: profileId, label: profileId };
}

function benchmarkProfileIds() {
  const ids = benchmarkProfiles().map((item) => item.id).filter((id) => id !== "full");
  if (elements.benchmarkIncludeFull.checked && !ids.includes("full")) ids.push("full");
  return ids.length ? ids : ["balanced"];
}

function persistBenchmarkResults() {
  try {
    localStorage.setItem("mykos-benchmark", JSON.stringify(state.benchmarkResults));
  } catch (_error) {
    // Los resultados son una comodidad local; la interfaz sigue funcionando si el almacenamiento está lleno.
  }
}

function loadBenchmarkResults() {
  try {
    const parsed = JSON.parse(localStorage.getItem("mykos-benchmark") || "{}");
    state.benchmarkResults = parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_error) {
    state.benchmarkResults = {};
  }
}

function formatMilliseconds(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "—";
  if (number >= 1000) return `${(number / 1000).toFixed(1)} s`;
  return `${Math.round(number)} ms`;
}

function formatRate(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number.toFixed(1)} tok/s` : "—";
}

function benchmarkRecommendation(results) {
  const valid = results.filter((item) => item.ok && Number(item.total_ms) > 0);
  if (!valid.length) return "Sin mediciones válidas.";
  const fastest = valid.reduce((best, item) => Number(item.tokens_per_second || 0) > Number(best.tokens_per_second || 0) ? item : best);
  const lowestLatency = valid.reduce((best, item) => Number(item.total_ms) < Number(best.total_ms) ? item : best);
  const maxRate = Math.max(...valid.map((item) => Number(item.tokens_per_second || 0)), 1);
  const minLatency = Math.min(...valid.map((item) => Number(item.total_ms)));
  const recommended = valid.reduce((best, item) => {
    const score = (Number(item.tokens_per_second || 0) / maxRate) * 0.65
      + (minLatency / Math.max(Number(item.total_ms), 1)) * 0.35;
    const bestScore = (Number(best.tokens_per_second || 0) / maxRate) * 0.65
      + (minLatency / Math.max(Number(best.total_ms), 1)) * 0.35;
    return score > bestScore ? item : best;
  });
  return `Mejor compromiso: ${recommended.label} · más rápido: ${fastest.label} · menor espera: ${lowestLatency.label}`;
}

function renderBenchmarkResults() {
  elements.benchmarkList.replaceChildren();
  const entries = Object.values(state.benchmarkResults)
    .filter((item) => item && Array.isArray(item.results))
    .sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")));
  if (!entries.length) {
    elements.benchmarkStatus.textContent = state.benchmarkBusy ? "Preparando medición…" : "Todavía no hay mediciones.";
    return;
  }

  for (const bundle of entries) {
    const card = document.createElement("article");
    card.className = "benchmark-card";
    const heading = document.createElement("div");
    heading.className = "benchmark-card-heading";
    const title = document.createElement("strong");
    title.textContent = bundle.model || "Modelo";
    const time = document.createElement("span");
    time.textContent = bundle.generated_at
      ? new Date(bundle.generated_at).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
      : "";
    heading.append(title, time);
    card.appendChild(heading);

    const summary = document.createElement("div");
    summary.className = "benchmark-summary";
    summary.textContent = benchmarkRecommendation(bundle.results);
    card.appendChild(summary);

    const table = document.createElement("table");
    table.className = "benchmark-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of ["Perfil", "Contexto", "Espera", "Salida", "Velocidad"]) {
      const cell = document.createElement("th");
      cell.textContent = label;
      headRow.appendChild(cell);
    }
    head.appendChild(headRow);
    table.appendChild(head);
    const body = document.createElement("tbody");
    for (const result of bundle.results) {
      const row = document.createElement("tr");
      const profileCell = document.createElement("td");
      profileCell.textContent = result.label || benchmarkProfile(result.profile).label;
      profileCell.title = result.error || result.description || "";
      const contextCell = document.createElement("td");
      contextCell.textContent = formatNumber(result.context);
      const latencyCell = document.createElement("td");
      latencyCell.textContent = result.ok ? formatMilliseconds(result.total_ms) : "error";
      const outputCell = document.createElement("td");
      outputCell.textContent = result.ok ? `${result.output_tokens || 0} tok` : "—";
      const rateCell = document.createElement("td");
      rateCell.textContent = result.ok ? formatRate(result.tokens_per_second) : (result.error || "error");
      if (!result.ok) row.className = "benchmark-error-row";
      row.append(profileCell, contextCell, latencyCell, outputCell, rateCell);
      body.appendChild(row);
    }
    table.appendChild(body);
    card.appendChild(table);
    elements.benchmarkList.appendChild(card);
  }
  elements.benchmarkStatus.textContent = `${entries.length} modelo${entries.length === 1 ? "" : "s"} medido${entries.length === 1 ? "" : "s"}.`;
}

function setBenchmarkBusy(busy) {
  state.benchmarkBusy = busy;
  elements.benchmarkCurrent.disabled = busy;
  elements.benchmarkAll.disabled = busy;
  elements.benchmarkIncludeFull.disabled = busy;
}

async function runBenchmarks(compareAll = false) {
  if (state.benchmarkBusy) return;
  const profiles = benchmarkProfileIds();
  const models = compareAll
    ? state.models.filter((item) => item.chat_capable && !item.remote)
    : state.models.filter((item) => item.name === selectedModel() && item.chat_capable && !item.remote);
  if (!models.length) {
    elements.benchmarkStatus.textContent = "Selecciona un modelo local; el benchmark no usa modelos remotos.";
    return;
  }

  setBenchmarkBusy(true);
  renderBenchmarkResults();
  try {
    for (const [index, model] of models.entries()) {
      elements.benchmarkStatus.textContent = `Midiendo ${index + 1}/${models.length}: ${model.name}…`;
      try {
        const data = await api("/api/benchmark", {
          method: "POST",
          body: JSON.stringify({ model: model.name, profiles }),
        });
        state.benchmarkResults[model.name] = {
          model: data.model,
          remote: data.remote,
          context_length: data.context_length,
          generated_at: new Date().toISOString(),
          results: data.results || [],
        };
      } catch (error) {
        state.benchmarkResults[model.name] = {
          model: model.name,
          generated_at: new Date().toISOString(),
          results: [{ profile: "error", label: "Medición", ok: false, error: error.message }],
        };
      }
      persistBenchmarkResults();
      renderBenchmarkResults();
    }
    elements.benchmarkStatus.textContent = `Medición terminada · ${models.length} modelo${models.length === 1 ? "" : "s"}.`;
  } finally {
    setBenchmarkBusy(false);
  }
}

function persistOllamaJobs() {
  localStorage.setItem("mykos-ollama-jobs", JSON.stringify(state.ollamaJobs.slice(-8)));
}

function renderOllamaInstalled() {
  elements.ollamaInstalledList.replaceChildren();
  const ollamaModels = state.models.filter((item) => item.provider === "ollama");
  if (!ollamaModels.length) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "No hay modelos instalados.";
    elements.ollamaInstalledList.appendChild(empty);
    return;
  }
  for (const model of ollamaModels) {
    const row = document.createElement("div");
    row.className = "ollama-model-row";
    const details = document.createElement("div");
    details.style.minWidth = "0";
    const name = document.createElement("div");
    name.className = "ollama-model-name";
    name.textContent = model.name;
    const meta = document.createElement("div");
    meta.className = "ollama-model-size";
    meta.textContent = [formatBytes(model.size), model.vision_capable ? "visión" : ""].filter(Boolean).join(" · ");
    details.append(name, meta);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ollama-action-button";
    remove.textContent = "Eliminar";
    remove.addEventListener("click", () => requestOllamaAction("/api/ollama/delete-request", model.name));
    row.append(details, remove);
    elements.ollamaInstalledList.appendChild(row);
  }
}

function renderOllamaCatalog() {
  elements.ollamaCatalogList.replaceChildren();
  if (!state.ollamaCatalog.length) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "No hay resultados para esa búsqueda.";
    elements.ollamaCatalogList.appendChild(empty);
    return;
  }
  const installedNames = new Set(
    state.models
      .filter((model) => model.provider === "ollama")
      .map((model) => model.name.split(":", 1)[0].toLowerCase()),
  );
  for (const item of state.ollamaCatalog) {
    const card = document.createElement("article");
    card.className = "ollama-catalog-card";
    const title = document.createElement("strong");
    title.textContent = item.name;
    card.appendChild(title);
    if (item.description) {
      const description = document.createElement("p");
      description.className = "ollama-catalog-description";
      description.textContent = item.description;
      card.appendChild(description);
    }
    const badges = document.createElement("div");
    badges.className = "ollama-catalog-badges";
    for (const badge of (item.badges || []).slice(0, 10)) {
      const element = document.createElement("span");
      element.className = "ollama-catalog-badge";
      element.textContent = badge;
      badges.appendChild(element);
    }
    card.appendChild(badges);
    const install = document.createElement("button");
    install.type = "button";
    install.className = "ollama-action-button";
    const installed = Boolean(item.installed) || installedNames.has(String(item.name).toLowerCase());
    install.textContent = installed ? "Instalado" : "Preparar descarga";
    install.disabled = installed;
    install.addEventListener("click", () => requestOllamaAction("/api/ollama/pull-request", item.name));
    card.appendChild(install);
    elements.ollamaCatalogList.appendChild(card);
  }
}

function renderOllamaJobs() {
  elements.ollamaJobList.replaceChildren();
  for (const job of state.ollamaJobs) {
    const card = document.createElement("div");
    card.className = "ollama-job";
    const title = document.createElement("strong");
    title.textContent = `${job.model} · ${job.status === "completed" ? "completado" : job.status === "failed" ? "error" : job.status === "awaiting_approval" ? "esperando aprobación" : "descargando"}`;
    const meta = document.createElement("div");
    meta.className = "ollama-job-meta";
    const progress = job.total ? ` · ${formatBytes(job.completed)} / ${formatBytes(job.total)} · ${job.percent || 0}%` : "";
    meta.textContent = `${job.message || ""}${progress}`;
    card.append(title, meta);
    if (job.status === "running" || job.status === "awaiting_approval") {
      const bar = document.createElement("div");
      bar.className = "ollama-progress";
      const fill = document.createElement("span");
      fill.style.width = `${Math.max(2, Math.min(100, Number(job.percent) || 0))}%`;
      bar.appendChild(fill);
      card.appendChild(bar);
    }
    elements.ollamaJobList.appendChild(card);
  }
}

function rememberOllamaJob(job) {
  if (!job?.id) return;
  const index = state.ollamaJobs.findIndex((item) => item.id === job.id);
  if (index >= 0) state.ollamaJobs[index] = job;
  else state.ollamaJobs.push(job);
  state.ollamaJobs = state.ollamaJobs.slice(-8);
  persistOllamaJobs();
  renderOllamaJobs();
  pollOllamaJob(job.id);
}

async function pollOllamaJob(jobId) {
  try {
    const data = await api(`/api/ollama/jobs?id=${encodeURIComponent(jobId)}`);
    const job = data.jobs?.[0];
    if (!job) return;
    const index = state.ollamaJobs.findIndex((item) => item.id === jobId);
    if (index >= 0) state.ollamaJobs[index] = job;
    else state.ollamaJobs.push(job);
    persistOllamaJobs();
    renderOllamaJobs();
    if (job.status === "running" || job.status === "awaiting_approval") {
      window.setTimeout(() => pollOllamaJob(jobId), 800);
    } else if (job.status === "completed") {
      await loadModels();
      renderOllamaInstalled();
    }
  } catch (_error) {
    // La consulta se reintentará al volver a abrir el panel.
  }
}

async function loadOllamaJobs() {
  try {
    state.ollamaJobs = JSON.parse(localStorage.getItem("mykos-ollama-jobs") || "[]");
    if (!Array.isArray(state.ollamaJobs)) state.ollamaJobs = [];
  } catch (_error) {
    state.ollamaJobs = [];
  }
  renderOllamaJobs();
  for (const job of state.ollamaJobs) pollOllamaJob(job.id);
}

async function searchOllamaCatalog() {
  elements.ollamaCatalogStatus.textContent = "Consultando catálogo público…";
  try {
    const query = elements.ollamaCatalogQuery.value.trim();
    const data = await api(`/api/ollama/catalog?query=${encodeURIComponent(query)}`);
    state.ollamaCatalog = data.models || [];
    elements.ollamaCatalogStatus.textContent = `${state.ollamaCatalog.length} resultados · catálogo de Ollama`;
    renderOllamaCatalog();
  } catch (error) {
    state.ollamaCatalog = [];
    elements.ollamaCatalogStatus.textContent = error.message;
    renderOllamaCatalog();
  }
}

function renderLibraryRoots() {
  elements.libraryRoot.replaceChildren();
  if (!state.allowedRoots.length) {
    const option = document.createElement("option");
    option.textContent = "Sin raíces autorizadas";
    option.value = "";
    elements.libraryRoot.appendChild(option);
    elements.libraryRoot.disabled = true;
    return;
  }
  elements.libraryRoot.disabled = false;
  for (const root of state.allowedRoots) {
    const option = document.createElement("option");
    option.value = root.name;
    option.textContent = root.name;
    elements.libraryRoot.appendChild(option);
  }
  if (!state.allowedRoots.some((root) => root.name === state.libraryRoot)) {
    state.libraryRoot = state.allowedRoots[0].name;
  }
  elements.libraryRoot.value = state.libraryRoot;
}

function libraryPathLabel(path) {
  return path && path !== "." ? path : "raíz";
}

function libraryParentPath(path) {
  const clean = String(path || ".").replace(/[\\/]+$/, "");
  if (!clean || clean === ".") return ".";
  const parts = clean.split(/[\\/]+/).filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

function renderLibraryList(items, searchResults = false) {
  elements.libraryList.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = searchResults ? "No se han encontrado coincidencias." : "Esta carpeta está vacía.";
    elements.libraryList.appendChild(empty);
    return;
  }

  if (!searchResults && state.libraryPath !== ".") {
    const parent = document.createElement("button");
    parent.type = "button";
    parent.className = "library-entry library-folder";
    parent.textContent = "..  Carpeta superior";
    parent.addEventListener("click", () => loadLibraryDirectory(libraryParentPath(state.libraryPath)));
    elements.libraryList.appendChild(parent);
  }

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "library-entry";
    const details = document.createElement("div");
    details.className = "library-entry-details";
    const name = document.createElement("strong");
    name.textContent = searchResults ? item.path : (String(item.path).split("/").pop() || item.path);
    const meta = document.createElement("span");
    if (searchResults) {
      meta.textContent = `Línea ${item.line || "?"}${item.snippet ? ` · ${item.snippet}` : ""}`;
    } else if (item.type === "directory") {
      meta.textContent = "Carpeta";
    } else {
      meta.textContent = [item.kind || "archivo", formatBytes(item.size)].filter(Boolean).join(" · ");
    }
    details.append(name, meta);
    row.appendChild(details);
    const action = document.createElement("button");
    action.type = "button";
    action.className = "ollama-action-button";
    if (!searchResults && item.type === "directory") {
      action.textContent = "Abrir";
      action.addEventListener("click", () => loadLibraryDirectory(item.path));
      row.classList.add("library-folder");
    } else if (item.previewable !== false || searchResults) {
      action.textContent = "Ver";
      action.addEventListener("click", () => previewLibraryFile(state.libraryRoot, item.path));
    } else {
      action.textContent = "No compatible";
      action.disabled = true;
    }
    row.appendChild(action);
    elements.libraryList.appendChild(row);
  }
}

async function loadLibraryDirectory(path = ".") {
  state.libraryPath = path || ".";
  elements.libraryPath.value = state.libraryPath;
  elements.libraryStatus.textContent = "Cargando carpeta…";
  try {
    const query = new URLSearchParams({ root: state.libraryRoot, path: state.libraryPath });
    const data = await api(`/api/library/list?${query.toString()}`);
    state.libraryItems = data.items || [];
    elements.libraryStatus.textContent = `${state.libraryItems.length} elementos · ${state.libraryRoot} / ${libraryPathLabel(data.path)}`;
    renderLibraryList(state.libraryItems);
  } catch (error) {
    state.libraryItems = [];
    elements.libraryStatus.textContent = error.message;
    renderLibraryList([]);
  }
}

async function searchLibrary() {
  const queryText = elements.librarySearchQuery.value.trim();
  if (!queryText) {
    loadLibraryDirectory(state.libraryPath);
    return;
  }
  elements.libraryStatus.textContent = "Buscando en archivos de texto…";
  try {
    const query = new URLSearchParams({ root: state.libraryRoot, path: state.libraryPath, query: queryText });
    const data = await api(`/api/library/search?${query.toString()}`);
    state.libraryResults = data.matches || [];
    elements.libraryStatus.textContent = `${state.libraryResults.length} coincidencias · ${data.files_scanned || 0} archivos revisados`;
    renderLibraryList(state.libraryResults, true);
  } catch (error) {
    state.libraryResults = [];
    elements.libraryStatus.textContent = error.message;
    renderLibraryList([] , true);
  }
}

async function previewLibraryFile(root, path) {
  elements.libraryPreview.hidden = false;
  elements.libraryPreview.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "panel-help";
  loading.textContent = "Abriendo archivo…";
  elements.libraryPreview.appendChild(loading);
  try {
    const query = new URLSearchParams({ root, path });
    const data = await api(`/api/library/preview?${query.toString()}`);
    elements.libraryPreview.replaceChildren();
    const heading = document.createElement("div");
    heading.className = "library-preview-heading";
    const title = document.createElement("strong");
    title.textContent = path;
    const use = document.createElement("button");
    use.type = "button";
    use.className = "ollama-action-button";
    use.textContent = "Usar en chat";
    use.addEventListener("click", () => {
      elements.input.value = `Analiza el archivo autorizado "${root}/${path}".`;
      elements.input.focus();
    });
    heading.append(title, use);
    elements.libraryPreview.appendChild(heading);
    if (data.image?.data) {
      const image = document.createElement("img");
      image.className = "library-preview-image";
      image.alt = path;
      image.src = `data:${data.image.mime_type};base64,${data.image.data}`;
      elements.libraryPreview.appendChild(image);
      const ocr = data.ocr?.text || "";
      if (ocr) {
        const ocrLabel = document.createElement("div");
        ocrLabel.className = "library-preview-label";
        ocrLabel.textContent = "OCR";
        const ocrText = document.createElement("pre");
        ocrText.textContent = ocr;
        elements.libraryPreview.append(ocrLabel, ocrText);
      }
    } else {
      const text = document.createElement("pre");
      text.textContent = data.text || "El archivo no contiene texto extraíble.";
      elements.libraryPreview.appendChild(text);
    }
  } catch (error) {
    const failure = document.createElement("div");
    failure.className = "error-text";
    failure.textContent = error.message;
    elements.libraryPreview.replaceChildren(failure);
  }
}

async function requestOllamaAction(endpoint, model) {
  try {
    const data = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ model, conversation_id: state.conversationId }),
    });
    if (data.approval && !state.pendingApprovals.some((item) => item.id === data.approval.id)) {
      state.pendingApprovals.push(data.approval);
      renderApprovals();
    }
    if (data.job) rememberOllamaJob(data.job);
  } catch (error) {
    addBubble("assistant", error.message, true);
  }
}

function renderAttachments() {
  elements.attachmentList.replaceChildren();
  for (const attachment of state.attachments) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    const label = document.createElement("span");
    label.textContent = `${attachment.name} · ${formatBytes(attachment.size)}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Quitar ${attachment.name}`);
    remove.addEventListener("click", () => {
      state.attachments = state.attachments.filter((item) => item.id !== attachment.id);
      renderAttachments();
    });
    chip.append(label, remove);
    elements.attachmentList.appendChild(chip);
  }
}

async function uploadFiles(files) {
  const selected = Array.from(files || []);
  if (!selected.length || state.busy) return;
  const form = new FormData();
  for (const file of selected.slice(0, 4 - state.attachments.length)) form.append("files", file, file.name);
  if (!form.has("files")) return;
  try {
    elements.dropzone.classList.add("dragging");
    const response = await fetch("/api/uploads", { method: "POST", body: form });
    const data = await response.json().catch(() => ({ error: "Respuesta inválida del servidor." }));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    state.attachments.push(...(data.attachments || []));
    renderAttachments();
  } catch (error) {
    const failure = document.createElement("div");
    failure.className = "attachment-error";
    failure.textContent = error.message;
    elements.attachmentList.replaceChildren(failure);
  } finally {
    elements.dropzone.classList.remove("dragging");
    elements.fileInput.value = "";
  }
}

function setVoiceButton(mode, detail = "") {
  const active = ["connecting", "listening", "hearing", "thinking", "speaking"].includes(mode);
  elements.voiceInputButton.classList.toggle("recording", active);
  elements.voiceInputButton.classList.toggle("speaking", mode === "thinking" || mode === "speaking");
  elements.voiceInputButton.disabled = false;
  elements.voiceInputButton.setAttribute("aria-pressed", String(active));
  elements.voiceInputLabel.textContent = mode === "connecting" ? "Conectando…" : mode === "thinking" ? "Pensando…" : state.localVoiceCall ? "Escuchando…" : "Voz";
  elements.voiceInputButton.title = detail || (state.localVoiceCall ? "Micrófono abierto; clic para terminar" : "Hablar con MyKOS (Whisper local)");
  if (elements.voiceHangupButton) elements.voiceHangupButton.hidden = !state.localVoiceCall;
  state.callVisualMode = ["connecting", "hearing", "thinking", "speaking"].includes(mode) ? mode : "listening";
  if (elements.voiceCallStage) {
    elements.voiceCallStage.classList.toggle("listening", mode === "hearing");
    elements.voiceCallStage.classList.toggle("speaking", mode === "speaking");
    if (!state.callVisual) elements.voiceCallStage.dataset.mode = state.callVisualMode; updateVoiceCompactBar(state.callVisualMode);
    if (state.localVoiceCall) {
      elements.voiceCallStatus.textContent = mode === "connecting" ? "Conectando…" : mode === "hearing" ? "Te escucho" : mode === "thinking" ? "Pensando…" : mode === "speaking" ? "MyKOS está hablando" : "En llamada";
      elements.voiceCallDetail.textContent = detail || (mode === "hearing" ? "Habla; al guardar silencio enviaré el turno automáticamente." : mode === "speaking" ? "Puedes interrumpirle hablando." : "El micrófono sigue abierto.");
    }
  }
}

function updateVoiceModeButton() {
  if (elements.voiceModeButton) elements.voiceModeButton.hidden = true;
}

// La interfaz heredada se retiró en la fase 5.3. La voz usa únicamente el contrato de llamadas de MyKOS.

function renderConversationList() {
  elements.conversationList.replaceChildren();
  elements.conversationCount.textContent = String(state.conversations.length);
  if (!state.conversations.length) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "Todavía no hay conversaciones.";
    elements.conversationList.appendChild(empty);
    return;
  }
  for (const conversation of state.conversations) {
    const entry = document.createElement("div");
    entry.className = "conversation-entry";
    const button = document.createElement("button");
    button.type = "button";
    button.className = `conversation-item${conversation.id === state.conversationId ? " active" : ""}`;
    button.title = conversation.preview || conversation.title;
    const title = document.createElement("strong");
    title.textContent = conversation.title || "Nueva conversación";
    const preview = document.createElement("span");
    preview.textContent = conversation.preview || "Sin mensajes todavía";
    button.append(title, preview);
    button.addEventListener("click", () => openConversation(conversation.id));
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "conversation-delete";
    deleteButton.title = "Eliminar conversación definitivamente";
    deleteButton.setAttribute("aria-label", `Eliminar ${conversation.title || "conversación"}`);
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", () => deleteConversation(conversation.id));
    entry.append(button, deleteButton);
    elements.conversationList.appendChild(entry);
  }
}

function toggleConversationList(forceState) {
  if (!elements.historySection) return;
  const isCurrentlyCollapsed = elements.historySection.classList.contains("collapsed");
  const willBeCollapsed = typeof forceState === "boolean" ? !forceState : !isCurrentlyCollapsed;
  elements.historySection.classList.toggle("collapsed", willBeCollapsed);
  if (elements.toggleConversations) {
    elements.toggleConversations.setAttribute("aria-expanded", String(!willBeCollapsed));
    elements.toggleConversations.title = willBeCollapsed ? "Mostrar conversaciones" : "Ocultar conversaciones";
    elements.toggleConversations.setAttribute("aria-label", elements.toggleConversations.title);
  }
  try {
    localStorage.setItem("mykos_conversations_collapsed", willBeCollapsed ? "1" : "0");
  } catch (_e) {}
}

function initConversationToggle() {
  if (!elements.toggleConversations || !elements.historySection) return;
  elements.toggleConversations.addEventListener("click", () => toggleConversationList());
  try {
    if (localStorage.getItem("mykos_conversations_collapsed") === "1") {
      toggleConversationList(false);
    }
  } catch (_e) {}
}

function sourceDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch (_error) {
    return "fuente web";
  }
}

function sourceDate(value) {
  if (!value) return "Consultada recientemente";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Consultada recientemente";
  return `Consultada el ${date.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" })}`;
}

function renderSourceCards(sources) {
  const validSources = Array.isArray(sources)
    ? sources.filter((source) => source && typeof source.url === "string" && /^https?:\/\//i.test(source.url)).slice(0, 12)
    : [];
  if (!validSources.length) return null;
  const panel = document.createElement("section");
  panel.className = "source-cards";
  panel.setAttribute("aria-label", "Fuentes consultadas");
  const heading = document.createElement("div");
  heading.className = "source-cards-heading";
  heading.textContent = "Fuentes consultadas";
  const list = document.createElement("div");
  list.className = "source-cards-list";
  for (const source of validSources) {
    const card = document.createElement("article");
    card.className = "source-card";
    const title = document.createElement("strong");
    title.className = "source-card-title";
    title.textContent = source.title || sourceDomain(source.url);
    const meta = document.createElement("span");
    meta.className = "source-card-meta";
    meta.textContent = `${sourceDomain(source.url)} · ${sourceDate(source.consulted_at)}`;
    card.append(title, meta);
    if (source.snippet) {
      const snippet = document.createElement("p");
      snippet.className = "source-card-snippet";
      snippet.textContent = source.snippet;
      card.appendChild(snippet);
    }
    const link = document.createElement("a");
    link.className = "source-card-link";
    const rawUrl = String(source.url || "").trim();
    link.href = /^https?:\/\//i.test(rawUrl) ? rawUrl : "#";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Abrir fuente ↗";
    card.appendChild(link);
    list.appendChild(card);
  }
  panel.append(heading, list);
  return panel;
}

function formatMessageTimestamp(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.day}/${values.month}/${values.year} · ${values.hour}:${values.minute}`;
}

function addBubble(role, content, isError = false, sources = [], createdAt = "", messageId = "", model = "", meta = "", telemetry = null) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  const bubble = document.createElement("div");
  bubble.className = `message-bubble${isError ? " error-bubble" : ""}`;
  const label = document.createElement("div");
  label.className = "message-role";
  label.textContent = role === "user" ? "Tú" : "MyKOS";
  const timestamp = document.createElement("div");
  timestamp.className = "message-timestamp";
  timestamp.textContent = formatMessageTimestamp(createdAt) + (role === "assistant" && model ? " • " + model : "") + (role === "assistant" && meta ? " • " + meta : "");
  const text = document.createElement("div");
  text.className = "message-text";
  const mediaRegex = /!\[([^\]]*)\]\(((?:data:image\/[a-zA-Z0-9+.-]+;base64,[A-Za-z0-9+/=]+)|(?:https?:\/\/[^\s)]+)|(?:\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp|gif|svg|mp4|webm)))\)/gi;
  let lastIndex = 0;
  let match;
  while ((match = mediaRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      text.appendChild(document.createTextNode(content.slice(lastIndex, match.index)));
    }
    const src = match[2];
    const isRemote = /^https?:\/\//i.test(src);
    if (isRemote) {
      // H3 auditoría: no cargar automáticamente recursos remotos para evitar exfiltración por inyección indirecta
      const link = document.createElement("a");
      link.className = "chat-external-media-link";
      link.href = src;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `🔗 [Ver medio externo: ${match[1] || "enlace"}]`;
      text.appendChild(link);
    } else if (/\.(?:mp4|webm)$/i.test(src)) {
      const vid = document.createElement("video");
      vid.className = "chat-inline-video";
      vid.src = src;
      vid.controls = true;
      vid.autoplay = true;
      vid.loop = true;
      vid.muted = true;
      vid.playsInline = true;
      text.appendChild(vid);
    } else {
      const img = document.createElement("img");
      img.className = "chat-inline-image";
      img.alt = match[1] || "Imagen generada";
      img.src = src;
      img.loading = "lazy";
      text.appendChild(img);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) {
    text.appendChild(document.createTextNode(content.slice(lastIndex)));
  }
  bubble.append(label, timestamp, text);
  if (role === "assistant") {
    if (telemetry && (telemetry.tokens_per_second > 0 || telemetry.tokens_out > 0)) {
      const telemEl = document.createElement("div");
      telemEl.className = "message-telemetry";
      const parts = [];
      if (telemetry.tokens_per_second > 0) parts.push(`⚡ ${telemetry.tokens_per_second} t/s`);
      if (telemetry.duration_ms > 0) parts.push(`${(telemetry.duration_ms / 1000).toFixed(1)}s`);
      if (telemetry.tokens_out > 0) parts.push(`${telemetry.tokens_out} tokens`);
      if (telemetry.prompt_tokens_per_second > 0) parts.push(`(ingesta: ${telemetry.prompt_tokens_per_second} t/s)`);
      telemEl.textContent = parts.join(" · ");
      bubble.appendChild(telemEl);
    }
    const sourceCards = renderSourceCards(sources);
    if (sourceCards) bubble.appendChild(sourceCards);
  }
  if (role === "user" && messageId && state.conversationId) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "message-delete";
    remove.textContent = "Eliminar mi mensaje";
    remove.addEventListener("click", () => deleteMessage(messageId));
    actions.appendChild(remove);
    bubble.appendChild(actions);
  }
  row.appendChild(bubble);
  elements.messages.appendChild(row);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return row;
}

function showWelcome() {
  elements.messages.replaceChildren();
  const welcome = document.createElement("div");
  welcome.className = "welcome";
  const title = document.createElement("div");
  title.className = "welcome-mykos";
  title.textContent = "MyKOS";
  welcome.appendChild(title);
  elements.messages.appendChild(welcome);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({ error: "Respuesta inválida del servidor." }));
  if (!response.ok) {
    const failure = new Error(data.error || `HTTP ${response.status}`);
    failure.serverMessage = typeof data.message === "string" ? data.message : "";
    throw failure;
  }
  return data;
}

function renderOAuthStatus(data = {}) {
  const providers = data.providers || [];
  state.oauthProviders = providers;
  state.oauth = Object.fromEntries(providers.filter((item) => item?.id).map((item) => [item.id, item]));
  renderProviderDirectory();
  renderClaudeOAuthStatus();
  renderOpenRouterOAuthStatus();
  renderMetaOAuthStatus();
  renderGrokStatus();
  renderNvidiaApiStatus();
  renderKimiApiStatus();
  renderGeminiApiStatus();
  renderMistralApiStatus();
  renderAntigravityCliStatus();
  renderQwenCliStatus();
  const openai = state.oauth.openai_codex_oauth || {};
  const openaiApi = state.oauth.openai_api || {};
  const login = state.oauth.openai_codex_oauth_login || {};
  const hasOAuth = Boolean(openai.has_oauth ?? (openai.authenticated && openai.auth_method !== "OpenAI API Key"));
  const hasApiKey = Boolean(openai.has_api_key || openaiApi.authenticated || openai.auth_method === "OpenAI API Key");

  if (login.status === "running" && !hasOAuth) {
    elements.oauthOpenaiLogout.hidden = !hasApiKey;
    elements.oauthStatus.replaceChildren();
    const textNode = document.createTextNode("Inicio de sesión abierto en Chrome; autoriza el acceso en OpenAI.");
    elements.oauthStatus.appendChild(textNode);
    if (login.user_code) {
      const codeSpan = document.createElement("span");
      codeSpan.textContent = ` · Código de dispositivo: ${login.user_code}`;
      codeSpan.style.fontWeight = "bold";
      elements.oauthStatus.appendChild(codeSpan);
    }
    if (login.login_url) {
      const link = document.createElement("a");
      link.href = login.login_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "oauth-login-link";
      link.textContent = "Abrir página de autorización de OpenAI";
      elements.oauthStatus.appendChild(document.createElement("br"));
      elements.oauthStatus.appendChild(link);
    }
    elements.oauthOpenai.textContent = "Esperando autorización…";
    elements.oauthOpenai.disabled = true;
    return;
  }

  if (hasOAuth || hasApiKey) {
    if (hasOAuth && hasApiKey) {
      elements.oauthStatus.textContent = "OpenAI conectado: Codex OAuth + API Key personal.";
      elements.oauthOpenai.textContent = "OAuth conectado";
      elements.oauthOpenai.disabled = true;
      if (elements.openaiApiToggle) elements.openaiApiToggle.textContent = "Cambiar API Key";
      if (elements.openaiModels) {
        elements.openaiModels.textContent = "Codex OAuth (GPT-5.6) y OpenAI API (openai/…) listos en el selector.";
      }
    } else if (hasOAuth) {
      elements.oauthStatus.textContent = "OpenAI Codex OAuth conectado en MyKOS.";
      elements.oauthOpenai.textContent = "OAuth conectado";
      elements.oauthOpenai.disabled = true;
      if (elements.openaiApiToggle) elements.openaiApiToggle.textContent = "Usar clave API";
      if (elements.openaiModels) {
        elements.openaiModels.textContent = "Modelos GPT-5.6 (Codex OAuth) listos en el selector principal.";
      }
    } else {
      const apiCount = state.models.filter((item) => item.provider === "openai_api").length;
      elements.oauthStatus.textContent = "OpenAI conectado mediante clave API personal.";
      elements.oauthOpenai.textContent = "Iniciar sesión OAuth (opcional)";
      elements.oauthOpenai.disabled = false;
      if (elements.openaiApiToggle) elements.openaiApiToggle.textContent = "Cambiar API Key";
      if (elements.openaiModels) {
        elements.openaiModels.textContent = apiCount
          ? `${apiCount} modelos OpenAI API (openai/…) listos en el selector principal.`
          : "Modelos GPT-4o, o1 y o3-mini listos en el selector principal.";
      }
    }
    elements.oauthOpenaiLogout.hidden = false;
    if (elements.openaiApiKeyRow) elements.openaiApiKeyRow.hidden = true;
  } else {
    elements.oauthStatus.textContent = openai.error || "OpenAI todavía no está conectado en MyKOS.";
    elements.oauthOpenai.textContent = "Iniciar sesión OAuth";
    elements.oauthOpenai.disabled = false;
    if (elements.openaiApiToggle) elements.openaiApiToggle.textContent = "Usar clave API";
    elements.oauthOpenaiLogout.hidden = true;
    if (elements.openaiModels) {
      elements.openaiModels.textContent = "Inicia sesión con OAuth oficial o introduce tu clave personal de OpenAI (sk-…).";
    }
  }
}

function renderClaudeOAuthStatus() {
  if (!elements.oauthClaudeStatus) return;
  const anthropicModels = state.models.filter((item) => item.provider === "anthropic_api");
  const claudeCliModel = state.models.find((item) => item.provider === "anthropic_oauth");
  const anthropicAuth = state.oauth?.anthropic_api || state.oauthProviders.find((item) => item.id === "anthropic_api") || {};
  const claudeAuth = state.oauth?.claude_oauth || state.oauthProviders.find((item) => item.id === "claude_oauth") || {};

  const directConnected = Boolean(anthropicAuth.authenticated || anthropicModels.length > 0);
  const cliConnected = Boolean(claudeAuth.authenticated || claudeCliModel?.chat_capable);

  if (directConnected && cliConnected) {
    elements.oauthClaudeStatus.textContent = `Anthropic API (${anthropicModels.length} modelos) + Claude Code OAuth conectados.`;
    if (elements.anthropicApiConnect) elements.anthropicApiConnect.textContent = "Actualizar API Key";
    if (elements.oauthClaude) {
      elements.oauthClaude.textContent = "OAuth conectado";
      elements.oauthClaude.disabled = true;
    }
    if (elements.oauthClaudeLogout) elements.oauthClaudeLogout.hidden = false;
    if (elements.anthropicApiKeyRow) elements.anthropicApiKeyRow.hidden = true;
    if (elements.anthropicApiModels) {
      elements.anthropicApiModels.textContent = ["Claude Sonnet (OAuth)", ...anthropicModels.map((m) => m.label || m.name)].join(" · ");
    }
  } else if (directConnected) {
    elements.oauthClaudeStatus.textContent = `Anthropic API conectada directamente en MyKOS. ${anthropicModels.length} modelos disponibles.`;
    if (elements.anthropicApiConnect) elements.anthropicApiConnect.textContent = "Actualizar modelos";
    if (elements.oauthClaude) {
      elements.oauthClaude.textContent = "OAuth (Claude Code)";
      elements.oauthClaude.disabled = false;
    }
    if (elements.oauthClaudeLogout) elements.oauthClaudeLogout.hidden = false;
    if (elements.anthropicApiKeyRow) elements.anthropicApiKeyRow.hidden = true;
    if (elements.anthropicApiModels) {
      elements.anthropicApiModels.textContent = anthropicModels.map((m) => m.label || m.name).join(" · ");
    }
  } else if (cliConnected) {
    elements.oauthClaudeStatus.textContent = claudeAuth.email
      ? `Claude Code OAuth conectado (${claudeAuth.email}).`
      : "Claude OAuth conectado mediante Claude Code.";
    if (elements.anthropicApiConnect) elements.anthropicApiConnect.textContent = "Conectar API Key";
    if (elements.oauthClaude) {
      elements.oauthClaude.textContent = "OAuth conectado";
      elements.oauthClaude.disabled = true;
    }
    if (elements.oauthClaudeLogout) elements.oauthClaudeLogout.hidden = false;
    if (elements.anthropicApiKeyRow) elements.anthropicApiKeyRow.hidden = true;
    if (elements.anthropicApiModels) elements.anthropicApiModels.textContent = "Claude Sonnet (OAuth)";
  } else {
    const errorMsg = anthropicAuth.error || claudeAuth.error || "Anthropic / Claude todavía no está conectado en MyKOS.";
    elements.oauthClaudeStatus.textContent = errorMsg;
    if (elements.anthropicApiConnect) elements.anthropicApiConnect.textContent = "Conectar API Key";
    if (elements.oauthClaude) {
      elements.oauthClaude.textContent = "Iniciar sesión OAuth";
      elements.oauthClaude.disabled = false;
    }
    if (elements.oauthClaudeLogout) elements.oauthClaudeLogout.hidden = true;
    if (elements.anthropicApiModels) {
      elements.anthropicApiModels.textContent = "Introduce una clave de Anthropic (sk-ant-…) o inicia sesión con Claude Code OAuth.";
    }
  }
}

function renderOpenRouterOAuthStatus() {
  const models = state.models.filter((item) => item.provider === "openrouter");
  const oauth = state.oauthProviders.find((item) => item.id === "openrouter_oauth") || {};
  const login = state.oauthProviders.find((item) => item.id === "openrouter_oauth_login") || {};
  const connected = Boolean(oauth.authenticated) || models.some((item) => item.chat_capable && item.auth_status === "autenticado");
  if (connected) {
    const isApiKey = oauth.auth_method === "OpenRouter API Key";
    elements.oauthOpenrouterStatus.textContent = isApiKey
      ? `OpenRouter conectado mediante clave API personal. ${models.length} modelos disponibles.`
      : `OpenRouter conectado mediante OAuth (PKCE). ${models.length} modelos disponibles.`;
    elements.oauthOpenrouter.textContent = "Actualizar modelos";
    elements.oauthOpenrouter.disabled = false;
    elements.oauthOpenrouterLogout.hidden = false;
    if (elements.openrouterApiKeyRow) elements.openrouterApiKeyRow.hidden = true;
    elements.oauthOpenrouterModels.textContent = "Los modelos aparecerán en el selector principal de Modelo.";
  } else if (login.status === "running") {
    elements.oauthOpenrouterStatus.textContent = "Esperando la autorización de OpenRouter…";
    elements.oauthOpenrouter.textContent = "Esperando autorización…";
    elements.oauthOpenrouter.disabled = true;
    elements.oauthOpenrouterLogout.hidden = true;
    elements.oauthOpenrouterModels.textContent = "Termina el acceso en la ventana de OpenRouter.";
  } else {
    elements.oauthOpenrouterStatus.textContent = oauth.error || "OpenRouter todavía no está conectado en MyKOS.";
    elements.oauthOpenrouter.textContent = "Iniciar sesión OAuth";
    elements.oauthOpenrouter.disabled = false;
    elements.oauthOpenrouterLogout.hidden = true;
    elements.oauthOpenrouterModels.textContent = "Inicia sesión con OAuth oficial o introduce tu clave personal de OpenRouter (sk-or-v1-…).";
  }
}

function renderMetaOAuthStatus() {
  if (!elements.oauthMetaStatus) return;
  const models = state.models.filter((item) => item.provider === "meta_ai_oauth" || item.provider === "meta_ai_api");
  const oauth = state.oauthProviders.find((item) => item.id === "meta_ai_oauth") || {};
  const login = state.oauthProviders.find((item) => item.id === "meta_ai_oauth_login") || {};
  const connected = Boolean(oauth.authenticated) || models.some((item) => item.chat_capable && item.auth_status === "autenticado");
  if (connected) {
    const methodDesc = oauth.auth_method || "Meta AI (Conectado)";
    elements.oauthMetaStatus.textContent = `Meta AI conectado mediante ${methodDesc}. ${models.length} modelos disponibles.`;
    elements.oauthMeta.textContent = "Actualizar modelos";
    elements.oauthMeta.disabled = false;
    elements.oauthMetaLogout.hidden = false;
    if (elements.metaApiKeyRow) elements.metaApiKeyRow.hidden = true;
    elements.oauthMetaModels.textContent = models.length
      ? models.map((item) => item.label || item.name).join(" · ")
      : "Los modelos de Meta AI aparecerán en el selector principal de Modelo.";
  } else if (login.running) {
    elements.oauthMetaStatus.textContent = "Negociando sesión OAuth con Meta AI (meta.ai)…";
    elements.oauthMeta.textContent = "Conectando…";
    elements.oauthMeta.disabled = true;
    elements.oauthMetaLogout.hidden = true;
    elements.oauthMetaModels.textContent = "Autorizando sesión OAuth y canal DGW con Meta AI.";
  } else {
    elements.oauthMetaStatus.textContent = login.error || oauth.error || "Meta AI todavía no está conectado en MyKOS.";
    elements.oauthMeta.textContent = "Conectar Meta AI OAuth";
    elements.oauthMeta.disabled = false;
    elements.oauthMetaLogout.hidden = true;
    elements.oauthMetaModels.textContent = "Vincula Meta AI por OAuth para Llama 4 gratis o introduce tu clave de Meta Model API para la serie Muse.";
  }
}

function renderGrokStatus() {
  if (!elements.grokStatus) return;
  const models = state.models.filter((item) => item.provider === "grok_oauth" || item.provider === "grok_api");
  const oauth = state.oauthProviders.find((item) => item.id === "grok_oauth") || {};
  const login = oauth.login || {};
  const connected = Boolean(oauth.authenticated) || models.some((item) => item.chat_capable && item.auth_status === "autenticado");

  if (connected) {
    const method = oauth.auth_method || (models[0]?.provider === "grok_oauth" ? "Grok OAuth (xAI)" : "Grok API Key");
    elements.grokStatus.textContent = `Grok (xAI) conectado mediante ${method}. ${models.length} modelos disponibles.`;
    elements.grokOauthConnect.textContent = "Actualizar modelos";
    elements.grokOauthConnect.disabled = false;
    elements.grokLogout.hidden = false;
    elements.grokApiToggle.hidden = true;
    elements.grokKeyRow.hidden = true;
    elements.grokModels.textContent = models.length
      ? models.map((item) => item.label || item.name).join(" · ")
      : "Los modelos de Grok aparecerán en el selector principal de Modelo.";
  } else if (login.status === "running") {
    elements.grokStatus.replaceChildren();
    const textNode = document.createTextNode("Autoriza MyKOS en xAI. ");
    elements.grokStatus.appendChild(textNode);
    if (login.user_code) {
      const codeSpan = document.createElement("span");
      codeSpan.textContent = `Código: ${login.user_code}`;
      codeSpan.style.fontWeight = "bold";
      elements.grokStatus.appendChild(codeSpan);
    }
    if (login.verification_uri_complete) {
      const link = document.createElement("a");
      link.href = login.verification_uri_complete;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "oauth-login-link";
      link.textContent = " · Abrir página de aprobación en xAI";
      elements.grokStatus.appendChild(link);
    }
    elements.grokOauthConnect.textContent = "Esperando aprobación…";
    elements.grokOauthConnect.disabled = true;
    elements.grokLogout.hidden = true;
    elements.grokModels.textContent = "Pulsa en el enlace de aprobación en xAI para autorizar MyKOS.";
  } else {
    elements.grokStatus.textContent = login.error || oauth.error || "Grok todavía no está conectado en MyKOS.";
    elements.grokOauthConnect.textContent = "Conectar xAI OAuth";
    elements.grokOauthConnect.disabled = false;
    elements.grokLogout.hidden = true;
    elements.grokApiToggle.hidden = false;
    elements.grokModels.textContent = "Conecta con tu cuenta de xAI o introduce tu clave personal de xAI (xai-…).";
  }
}

function renderNvidiaApiStatus() {
  if (!elements.nvidiaApiStatus) return;
  const models = state.models.filter((item) => item.provider === "nvidia_api");
  const auth = state.oauth?.nvidia_api || {};
  const connected = Boolean(auth.authenticated || models.some((item) => item.auth_status === "autenticado"));
  elements.nvidiaApiStatus.textContent = connected
    ? `NVIDIA NIM conectada directamente desde MyKOS. ${models.length} modelos disponibles.`
    : (auth.error || "NVIDIA NIM todavía no está conectada en MyKOS.");
  elements.nvidiaApiModels.textContent = models.length
    ? models.map((item) => item.label || item.name).join(" · ")
    : "Abre el catálogo, genera una clave personal y guárdala aquí para cargar los modelos.";
  if (elements.nvidiaApiConnect) {
    elements.nvidiaApiConnect.textContent = connected ? "Actualizar modelos" : "Conectar NVIDIA";
    elements.nvidiaApiConnect.disabled = false;
  }
  if (elements.nvidiaApiLogout) elements.nvidiaApiLogout.hidden = !connected;
  if (connected && elements.nvidiaApiKeyRow) elements.nvidiaApiKeyRow.hidden = true;
}

function renderKimiApiStatus() {
  if (!elements.kimiApiStatus) return;
  const models = state.models.filter((item) => item.provider === "kimi_api");
  const auth = state.oauth?.kimi_api || {};
  const connected = Boolean(auth.authenticated || models.some((item) => item.auth_status === "autenticado"));
  elements.kimiApiStatus.textContent = connected
    ? `Kimi conectada directamente desde MyKOS. ${models.length} modelos disponibles.`
    : (auth.error || "Kimi todavía no está conectada en MyKOS.");
  elements.kimiApiModels.textContent = models.length ? models.map((item) => item.label || item.name).join(" · ") : "Genera una clave personal en Kimi y guárdala aquí para cargar su catálogo.";
  elements.kimiApiConnect.textContent = connected ? "Actualizar modelos" : "Conectar Kimi";
  elements.kimiApiLogout.hidden = !connected;
  if (connected) elements.kimiApiKeyRow.hidden = true;
}


function renderGeminiApiStatus() {
  if (!elements.geminiApiStatus) return;
  const models = state.models.filter((item) => item.provider === "gemini_api");
  const auth = state.oauth?.gemini_api || {};
  const connected = Boolean(auth.authenticated || models.some((item) => item.auth_status === "autenticado"));
  elements.geminiApiStatus.textContent = connected
    ? `Gemini conectada directamente desde Google AI Studio. ${models.length} modelos disponibles.`
    : (auth.error || "Gemini todavía no está conectada en MyKOS.");
  elements.geminiApiModels.textContent = models.length ? models.map((item) => item.label || item.name).join(" · ") : "Genera una API key en Google AI Studio y guárdala aquí para cargar su catálogo.";
  elements.geminiApiConnect.textContent = connected ? "Actualizar modelos" : "Conectar Gemini";
  elements.geminiApiLogout.hidden = !connected;
  if (connected) elements.geminiApiKeyRow.hidden = true;
}

function renderMistralApiStatus() {
  if (!elements.mistralApiStatus) return;
  const models = state.models.filter((item) => item.provider === "mistral_api");
  const auth = state.oauthProviders.find((item) => item.id === "mistral_api") || {};
  const connected = Boolean(auth.authenticated || models.length > 0);
  elements.mistralApiStatus.textContent = connected
    ? `Mistral conectada en MyKOS. ${models.length} modelos disponibles.`
    : (auth.error || "Mistral todavía no está conectado en MyKOS.");
  if (elements.mistralApiModels) {
    elements.mistralApiModels.textContent = models.length
      ? models.map((m) => m.label || m.name).join(" · ")
      : "Introduce una clave de Mistral (mstrl_…) o pulsa «Vincular sesión Vibe» si ya usas Vibe en este equipo.";
  }
  if (elements.mistralApiConnect) {
    elements.mistralApiConnect.textContent = connected ? "Actualizar modelos" : "Conectar Mistral";
  }
  if (elements.mistralApiLogout) elements.mistralApiLogout.hidden = !connected;
  if (elements.mistralApiVibe) elements.mistralApiVibe.hidden = connected;
  if (connected && elements.mistralApiKeyRow) elements.mistralApiKeyRow.hidden = true;
}

function isAntigravityEnabled() {
  const auth = state.oauth?.antigravity_cli || state.oauth?.antigravity || state.oauthProviders.find((item) => item.id === "antigravity_cli");
  if (auth && typeof auth.enabled === "boolean") return auth.enabled;
  return state.models.some((item) => item.provider === "antigravity_cli");
}

function renderAntigravityCliStatus() {
  if (!elements.antigravityCliStatus) return;
  const models = state.models.filter((item) => item.provider === "antigravity_cli");
  const auth = state.oauth?.antigravity_cli || state.oauthProviders.find((item) => item.id === "antigravity_cli") || {};
  const enabled = isAntigravityEnabled();
  elements.antigravityCliStatus.textContent = enabled
    ? `Antigravity CLI activo mediante sesión de Google. ${models.length} modelos disponibles.`
    : (auth.error || "Antigravity CLI está desactivado en MyKOS.");
  if (elements.antigravityCliModels) {
    elements.antigravityCliModels.textContent = models.length
      ? models.map((m) => m.label || m.name).join(" · ")
      : "Al activarlo, se exponen los modelos de la sesión local de Google gestionada por agy.";
  }
  if (elements.antigravityCliToggle) {
    elements.antigravityCliToggle.textContent = enabled ? "Desactivar Antigravity" : "Activar Antigravity";
  }
}

function isQwenCliEnabled() {
  const auth = state.oauth?.qwen_cli || state.oauthProviders.find((item) => item.id === "qwen_cli");
  if (auth && typeof auth.enabled === "boolean") return auth.enabled;
  return state.models.some((item) => item.provider === "qwen_cli");
}

function renderQwenCliStatus() {
  if (!elements.qwenCliStatus) return;
  const models = state.models.filter((item) => item.provider === "qwen_cli");
  const auth = state.oauth?.qwen_cli || state.oauthProviders.find((item) => item.id === "qwen_cli") || {};
  const enabled = isQwenCliEnabled();
  elements.qwenCliStatus.textContent = enabled
    ? `Qwen Code CLI activo. ${models.length} modelos disponibles.`
    : (auth.error || "Qwen Code CLI está desactivado en MyKOS.");
  if (elements.qwenCliModels) {
    elements.qwenCliModels.textContent = models.length
      ? models.map((m) => m.label || m.name).join(" · ")
      : "Al activarlo, se exponen los modelos gestionados por el CLI oficial de Qwen Code.";
  }
  if (elements.qwenCliToggle) {
    elements.qwenCliToggle.textContent = enabled ? "Desactivar Qwen Code" : "Activar Qwen Code";
  }
}

function providerLabel(provider, models) {
  const labels = {
    strata: "Strata · GPU CUDA",
    ollama: "Ollama",
    llama_cpp: "llama.cpp · CUDA",
    anthropic_oauth: "Anthropic · Claude OAuth",
    anthropic_api: "Anthropic · Direct API",
    openai_codex_oauth: "OpenAI · Codex OAuth",
    openai_api: "OpenAI · API Key",
    nvidia_api: "NVIDIA NIM · API",
    kimi_api: "Kimi · API",
    gemini_api: "Gemini · API",
    mistral_api: "Mistral · API / Vibe",
    antigravity_cli: "Antigravity CLI · Google",
    qwen_cli: "Qwen Code · CLI",
    meta_ai_oauth: "Meta AI · OAuth",
    meta_ai_api: "Meta AI · API",
    grok_oauth: "Grok · xAI (OAuth)",
    grok_api: "Grok · xAI (API)",
    openrouter: "OpenRouter",
  };
  return labels[provider] || models[0]?.provider_label || provider || "Proveedor";
}

function renderProviderDirectory() {
  if (!elements.providerDirectoryList) return;
  elements.providerDirectoryList.replaceChildren();
  const grouped = new Map();
  for (const model of state.models) {
    const provider = String(model.provider || "unknown");
    if (!grouped.has(provider)) grouped.set(provider, []);
    grouped.get(provider).push(model);
  }
  if (!grouped.size) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "Cargando proveedores…";
    elements.providerDirectoryList.appendChild(empty);
    return;
  }
  const oauthById = new Map(state.oauthProviders.map((item) => [item.id, item]));
  for (const [provider, models] of grouped) {
    const card = document.createElement("article");
    card.className = "provider-card";
    const heading = document.createElement("div");
    heading.className = "provider-card-heading";
    const title = document.createElement("strong");
    title.textContent = providerLabel(provider, models);
    const status = document.createElement("span");
    const oauth = oauthById.get(provider);
    const codexConnected = Boolean(oauth?.has_oauth ?? (oauth?.authenticated && oauth?.auth_method !== "OpenAI API Key"));
    const connected = provider === "openai_codex_oauth"
      ? codexConnected
      : models.some((model) => model.auth_status === "autenticado" || !model.remote);
    status.className = `provider-status ${connected ? "connected" : "available"}`;
    status.textContent = connected ? "Disponible" : "Requiere conexión";
    heading.append(title, status);
    card.appendChild(heading);
    const mode = document.createElement("div");
    mode.className = "provider-card-mode";
    mode.textContent = provider.endsWith("oauth") ? "OAuth" : models.some((model) => model.remote) ? "Remoto" : "Local";
    card.appendChild(mode);
    const modelList = document.createElement("div");
    modelList.className = "provider-model-list";
    for (const model of models) {
      const row = document.createElement("div");
      row.className = "provider-model-row";
      const name = document.createElement("span");
      name.textContent = model.label || model.name;
      const select = document.createElement("button");
      select.type = "button";
      select.className = "ollama-action-button";
      select.textContent = model.name === selectedModel() ? "Seleccionado" : "Usar";
      select.disabled = model.name === selectedModel() || !model.chat_capable;
      select.addEventListener("click", () => {
        elements.model.value = model.name;
        elements.model.dispatchEvent(new Event("change", { bubbles: true }));
      });
      row.append(name, select);
      modelList.appendChild(row);
    }
    card.appendChild(modelList);
    if (provider === "openai_codex_oauth" && !codexConnected) {
      const connect = document.createElement("button");
      connect.type = "button";
      connect.className = "ollama-action-button provider-connect";
      connect.textContent = "Conectar con OAuth";
      connect.addEventListener("click", startOpenAIAuth);
      card.appendChild(connect);
    }
    elements.providerDirectoryList.appendChild(card);
  }
}

async function loadOAuthStatus() {
  try {
    renderOAuthStatus(await api("/api/oauth/status"));
  } catch (error) {
    elements.oauthStatus.textContent = error.message;
    elements.oauthClaudeStatus.textContent = error.message;
  }
}

function stopOAuthPoll(key) {
  if (state.oauthPollTimers[key]) {
    window.clearTimeout(state.oauthPollTimers[key]);
    delete state.oauthPollTimers[key];
  }
  state.oauthPollSeq[key] = (state.oauthPollSeq[key] || 0) + 1;
}

function startOAuthPoll(key, tickFn, { initialDelayMs = 1500, intervalMs = 2000, maxDurationMs = 120000, onTimeout } = {}) {
  stopOAuthPoll(key);
  const seq = state.oauthPollSeq[key];
  const startedAt = Date.now();
  const schedule = (delayMs) => {
    state.oauthPollTimers[key] = window.setTimeout(runTick, delayMs);
  };
  const runTick = async () => {
    if (state.oauthPollSeq[key] !== seq) return;
    if (Date.now() - startedAt >= maxDurationMs) {
      stopOAuthPoll(key);
      await onTimeout?.();
      return;
    }
    let keepGoing = false;
    try {
      keepGoing = Boolean(await tickFn());
    } catch {
      keepGoing = false;
    }
    if (state.oauthPollSeq[key] === seq && keepGoing) {
      schedule(intervalMs);
    } else if (state.oauthPollSeq[key] === seq) {
      stopOAuthPoll(key);
    }
  };
  schedule(initialDelayMs);
}

async function startClaudeAuth() {
  elements.oauthClaude.disabled = true;
  try {
    await api("/api/oauth/claude/start", { method: "POST", body: JSON.stringify({ provider: "anthropic_oauth" }) });
    elements.oauthClaudeStatus.textContent = "Inicio de sesión de Claude abierto. Esperando autorización…";
    startOAuthPoll(
      "claude",
      async () => {
        await loadOAuthStatus();
        const claudeAuth = state.oauth?.claude_oauth || {};
        if (claudeAuth.authenticated) {
          await loadModels();
          return false;
        }
        return true;
      },
      {
        initialDelayMs: 1500,
        intervalMs: 2500,
        maxDurationMs: 120000,
        onTimeout: () => {
          elements.oauthClaudeStatus.textContent = "El inicio de sesión de Claude ha expirado (120 s).";
          elements.oauthClaude.disabled = false;
        },
      },
    );
  } catch (error) {
    elements.oauthClaudeStatus.textContent = error.message;
    elements.oauthClaude.disabled = false;
  }
}

async function startOpenRouterAuth() {
  elements.oauthOpenrouter.disabled = true;
  try {
    const connected = state.models.some((item) => item.provider === "openrouter" && item.auth_status === "autenticado");
    if (connected) {
      await api("/api/oauth/openrouter/refresh", { method: "POST", body: JSON.stringify({ provider: "openrouter" }) });
      await Promise.all([loadModels(), loadOAuthStatus()]);
      elements.oauthOpenrouter.disabled = false;
      return;
    }
    const data = await api("/api/oauth/openrouter/start", { method: "POST", body: JSON.stringify({ provider: "openrouter" }) });
    if (data.login_url) {
      const popup = window.open(data.login_url, "mykos-openrouter-oauth", "popup,width=520,height=720,resizable=yes,scrollbars=yes");
      if (!popup) window.location.assign(data.login_url);
    }
    renderOpenRouterOAuthStatus();
    startOAuthPoll(
      "openrouter",
      async () => {
        await loadOAuthStatus();
        const oauth = state.oauthProviders.find((item) => item.id === "openrouter_oauth") || {};
        const login = state.oauthProviders.find((item) => item.id === "openrouter_oauth_login") || {};
        if (oauth.authenticated) {
          await loadModels();
          elements.oauthOpenrouter.disabled = false;
          return false;
        }
        if (login.status !== "running") {
          elements.oauthOpenrouter.disabled = false;
          return false;
        }
        return true;
      },
      {
        initialDelayMs: 1500,
        intervalMs: 2000,
        maxDurationMs: 120000,
        onTimeout: () => {
          elements.oauthOpenrouterStatus.textContent = "El inicio de sesión de OpenRouter ha expirado (120 s).";
          elements.oauthOpenrouter.disabled = false;
        },
      },
    );
  } catch (error) {
    elements.oauthOpenrouterStatus.textContent = error.message;
    elements.oauthOpenrouter.disabled = false;
  }
}

async function logoutOAuth(provider, statusElement, logoutButton) {
  if (!window.confirm(`¿Desconectar ${provider} de MyKOS?`)) return;
  stopOAuthPoll(provider);
  logoutButton.disabled = true;
  try {
    const payloadProvider = provider === "openai"
      ? "openai"
      : (provider === "claude" ? "anthropic_oauth" : (provider === "meta" ? "meta_ai_oauth" : provider));
    await api(`/api/oauth/${provider}/logout`, { method: "POST", body: JSON.stringify({ provider: payloadProvider }) });
    statusElement.textContent = `${provider} desconectado de MyKOS.`;
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    statusElement.textContent = error.message;
  } finally {
    logoutButton.disabled = false;
  }
}

async function startOpenAIAuth() {
  elements.oauthOpenai.disabled = true;
  try {
    const data = await api("/api/oauth/openai/start", { method: "POST", body: JSON.stringify({ provider: "openai_codex_oauth" }) });
    const preserved = (state.oauthProviders || []).filter(
      (item) => item.id !== "openai_codex_oauth" && item.id !== "openai_codex_oauth_login"
    );
    const prevOpenai = state.oauth?.openai_codex_oauth || {};
    renderOAuthStatus({
      providers: [
        ...preserved,
        { ...prevOpenai, id: "openai_codex_oauth", has_oauth: false, error: "Esperando autorización…" },
        { id: "openai_codex_oauth_login", ...data },
      ],
    });
    startOAuthPoll(
      "openai",
      async () => {
        await loadOAuthStatus();
        const login = state.oauth?.openai_codex_oauth_login || {};
        const openai = state.oauth?.openai_codex_oauth || {};
        const hasOAuth = Boolean(openai?.has_oauth ?? (openai?.authenticated && openai?.auth_method !== "OpenAI API Key"));
        if (login?.status === "running" && !hasOAuth) return true;
        await loadModels();
        elements.oauthOpenai.disabled = false;
        return false;
      },
      {
        initialDelayMs: 1500,
        intervalMs: 2000,
        maxDurationMs: 120000,
        onTimeout: () => {
          elements.oauthStatus.textContent = "El inicio de sesión de OpenAI ha expirado (120 s).";
          elements.oauthOpenai.disabled = false;
        },
      },
    );
  } catch (error) {
    elements.oauthStatus.textContent = error.message;
    elements.oauthOpenai.disabled = false;
  }
}

elements.oauthOpenai?.addEventListener("click", startOpenAIAuth);
elements.openaiApiToggle?.addEventListener("click", () => {
  if (!elements.openaiApiKeyRow) return;
  elements.openaiApiKeyRow.hidden = !elements.openaiApiKeyRow.hidden;
  if (!elements.openaiApiKeyRow.hidden && elements.openaiApiKey) {
    elements.openaiApiKey.focus();
  }
});
elements.openaiApiSave?.addEventListener("click", async () => {
  const key = elements.openaiApiKey?.value?.trim();
  if (!key) {
    elements.oauthStatus.textContent = "Introduce una clave válida de OpenAI (sk-…).";
    return;
  }
  elements.openaiApiSave.disabled = true;
  try {
    elements.oauthStatus.textContent = "Validando y guardando clave de OpenAI…";
    await api("/api/oauth/openai/start", {
      method: "POST",
      body: JSON.stringify({ provider: "openai_codex_oauth", api_key: key }),
    });
    elements.openaiApiKeyRow.hidden = true;
    if (elements.openaiApiKey) elements.openaiApiKey.value = "";
    await loadModels();
    await loadOAuthStatus();
  } catch (error) {
    elements.oauthStatus.textContent = error.message;
  } finally {
    elements.openaiApiSave.disabled = false;
  }
});
elements.oauthOpenaiLogout?.addEventListener("click", () => logoutOAuth("openai", elements.oauthStatus, elements.oauthOpenaiLogout));
elements.oauthRefresh?.addEventListener("click", async () => {
  if (elements.oauthRefresh) elements.oauthRefresh.disabled = true;
  try {
    await api("/api/oauth/openai/refresh", { method: "POST", body: JSON.stringify({ provider: "openai_codex_oauth" }) });
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    if (elements.oauthStatus) elements.oauthStatus.textContent = error.message;
  } finally {
    if (elements.oauthRefresh) elements.oauthRefresh.disabled = false;
  }
});
elements.oauthClaude?.addEventListener("click", startClaudeAuth);
elements.oauthClaudeLogout?.addEventListener("click", async () => {
  const isAnthropicApi = Boolean(state.oauth?.anthropic_api?.authenticated || state.models.some((item) => item.provider === "anthropic_api" && item.auth_status === "autenticado"));
  const isClaudeOAuth = Boolean(state.oauth?.claude_oauth?.authenticated || state.models.some((item) => item.provider === "anthropic_oauth" && item.chat_capable));
  if (isAnthropicApi && isClaudeOAuth) {
    if (!window.confirm("¿Desconectar Anthropic API y Claude Code OAuth de MyKOS?")) return;
    elements.oauthClaudeLogout.disabled = true;
    try {
      await api("/api/providers/anthropic/logout", { method: "POST", body: JSON.stringify({ provider: "anthropic_api" }) });
      await api("/api/oauth/claude/logout", { method: "POST", body: JSON.stringify({ provider: "anthropic_oauth" }) });
      elements.oauthClaudeStatus.textContent = "Anthropic API y Claude OAuth desconectados de MyKOS.";
      await Promise.all([loadModels(), loadOAuthStatus()]);
    } catch (error) {
      elements.oauthClaudeStatus.textContent = error.message;
    } finally {
      elements.oauthClaudeLogout.disabled = false;
    }
  } else if (isAnthropicApi) {
    if (!window.confirm("¿Desconectar la clave de Anthropic de MyKOS?")) return;
    elements.oauthClaudeLogout.disabled = true;
    try {
      await api("/api/providers/anthropic/logout", { method: "POST", body: JSON.stringify({ provider: "anthropic_api" }) });
      elements.oauthClaudeStatus.textContent = "Anthropic desconectado de MyKOS.";
      await Promise.all([loadModels(), loadOAuthStatus()]);
    } catch (error) {
      elements.oauthClaudeStatus.textContent = error.message;
    } finally {
      elements.oauthClaudeLogout.disabled = false;
    }
  } else {
    logoutOAuth("claude", elements.oauthClaudeStatus, elements.oauthClaudeLogout);
  }
});
elements.oauthClaudeRefresh?.addEventListener("click", async () => {
  if (elements.oauthClaudeRefresh) elements.oauthClaudeRefresh.disabled = true;
  try {
    await api("/api/oauth/claude/refresh", { method: "POST", body: JSON.stringify({ provider: "anthropic_oauth" }) });
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    if (elements.oauthClaudeStatus) elements.oauthClaudeStatus.textContent = error.message;
  } finally {
    if (elements.oauthClaudeRefresh) elements.oauthClaudeRefresh.disabled = false;
  }
});
elements.anthropicApiConnect?.addEventListener("click", () => {
  const connected = state.models.some((item) => item.provider === "anthropic_api" && item.auth_status === "autenticado");
  if (connected) {
    elements.anthropicApiKeyRow.hidden = !elements.anthropicApiKeyRow.hidden;
    if (!elements.anthropicApiKeyRow.hidden && elements.anthropicApiKey) elements.anthropicApiKey.focus();
    return;
  }
  elements.anthropicApiKeyRow.hidden = false;
  elements.anthropicApiKey.focus();
});
elements.anthropicApiSave?.addEventListener("click", async () => {
  const apiKey = elements.anthropicApiKey.value.trim();
  if (!apiKey) {
    elements.oauthClaudeStatus.textContent = "Introduce la clave personal de Anthropic (sk-ant-…).";
    return;
  }
  elements.anthropicApiSave.disabled = true;
  elements.oauthClaudeStatus.textContent = "Validando la clave con Anthropic…";
  try {
    await api("/api/providers/anthropic/connect", {
      method: "POST",
      body: JSON.stringify({ provider: "anthropic_api", api_key: apiKey }),
    });
    elements.anthropicApiKey.value = "";
    elements.anthropicApiKeyRow.hidden = true;
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    elements.oauthClaudeStatus.textContent = error.message;
  } finally {
    elements.anthropicApiSave.disabled = false;
  }
});
elements.oauthOpenrouter?.addEventListener("click", startOpenRouterAuth);
elements.openrouterApiToggle?.addEventListener("click", () => {
  if (!elements.openrouterApiKeyRow) return;
  elements.openrouterApiKeyRow.hidden = !elements.openrouterApiKeyRow.hidden;
  if (!elements.openrouterApiKeyRow.hidden && elements.openrouterApiKey) {
    elements.openrouterApiKey.focus();
  }
});
elements.openrouterApiSave?.addEventListener("click", async () => {
  const key = elements.openrouterApiKey?.value?.trim();
  if (!key) {
    elements.oauthOpenrouterStatus.textContent = "Introduce una clave válida de OpenRouter (sk-or-v1-…).";
    return;
  }
  elements.openrouterApiSave.disabled = true;
  try {
    elements.oauthOpenrouterStatus.textContent = "Validando y guardando credencial de OpenRouter…";
    await api("/api/oauth/openrouter/start", {
      method: "POST",
      body: JSON.stringify({ provider: "openrouter", api_key: key }),
    });
    elements.openrouterApiKeyRow.hidden = true;
    if (elements.openrouterApiKey) elements.openrouterApiKey.value = "";
    await loadModels();
    await loadOAuthStatus();
  } catch (error) {
    elements.oauthOpenrouterStatus.textContent = error.message;
  } finally {
    elements.openrouterApiSave.disabled = false;
  }
});
elements.oauthOpenrouterLogout?.addEventListener("click", () => logoutOAuth("openrouter", elements.oauthOpenrouterStatus, elements.oauthOpenrouterLogout));
elements.oauthOpenrouterRefresh?.addEventListener("click", async () => {
  try {
    await api("/api/oauth/openrouter/refresh", { method: "POST", body: JSON.stringify({ provider: "openrouter" }) });
    await loadModels();
  } catch (error) {
    elements.oauthOpenrouterStatus.textContent = error.message;
  }
});

async function startMetaAuth() {
  if (!elements.oauthMeta) return;
  elements.oauthMeta.disabled = true;
  try {
    const connected = state.models.some((item) => (item.provider === "meta_ai_oauth" || item.provider === "meta_ai_api") && item.auth_status === "autenticado");
    if (connected) {
      await api("/api/oauth/meta/refresh", { method: "POST", body: JSON.stringify({ provider: "meta_ai_oauth" }) });
      await loadModels();
      return;
    }
    elements.oauthMetaStatus.textContent = "Conectando OAuth con Meta AI (meta.ai)…";
    await api("/api/oauth/meta/start", { method: "POST", body: JSON.stringify({ provider: "meta_ai_oauth" }) });
    await loadModels();
  } catch (error) {
    elements.oauthMetaStatus.textContent = error.message;
    elements.oauthMeta.disabled = false;
  }
}

elements.oauthMeta?.addEventListener("click", startMetaAuth);
elements.metaApiToggle?.addEventListener("click", () => {
  if (!elements.metaApiKeyRow) return;
  elements.metaApiKeyRow.hidden = !elements.metaApiKeyRow.hidden;
  if (!elements.metaApiKeyRow.hidden && elements.metaApiKey) {
    elements.metaApiKey.focus();
  }
});
elements.metaApiSave?.addEventListener("click", async () => {
  const key = elements.metaApiKey?.value?.trim();
  if (!key) {
    elements.oauthMetaStatus.textContent = "Introduce una clave válida de Meta Model API.";
    return;
  }
  elements.metaApiSave.disabled = true;
  try {
    elements.oauthMetaStatus.textContent = "Validando y guardando credencial de Meta AI…";
    await api("/api/oauth/meta/start", {
      method: "POST",
      body: JSON.stringify({ provider: "meta_ai_oauth", api_key: key }),
    });
    elements.metaApiKeyRow.hidden = true;
    if (elements.metaApiKey) elements.metaApiKey.value = "";
    await loadModels();
    await loadOAuthStatus();
  } catch (error) {
    elements.oauthMetaStatus.textContent = error.message;
  } finally {
    elements.metaApiSave.disabled = false;
  }
});
elements.oauthMetaLogout?.addEventListener("click", () => logoutOAuth("meta", elements.oauthMetaStatus, elements.oauthMetaLogout));
elements.oauthMetaRefresh?.addEventListener("click", async () => {
  try {
    await api("/api/oauth/meta/refresh", { method: "POST", body: JSON.stringify({ provider: "meta_ai_oauth" }) });
    await loadModels();
  } catch (error) {
    elements.oauthMetaStatus.textContent = error.message;
  }
});

async function startGrokAuth() {
  if (!elements.grokOauthConnect) return;
  elements.grokOauthConnect.disabled = true;
  try {
    const connected = state.models.some((item) => (item.provider === "grok_oauth" || item.provider === "grok_api") && item.auth_status === "autenticado");
    if (connected) {
      await api("/api/oauth/grok/refresh", { method: "POST", body: JSON.stringify({ provider: "grok_oauth" }) });
      await loadModels();
      return;
    }
    elements.grokStatus.textContent = "Iniciando autorización con xAI (Grok)…";
    const res = await api("/api/oauth/grok/start", { method: "POST", body: JSON.stringify({ provider: "grok_oauth" }) });
    if (res?.verification_uri_complete) {
      window.open(res.verification_uri_complete, "_blank", "width=600,height=720");
    }
    await loadOAuthStatus();
    startOAuthPoll(
      "grok",
      async () => {
        await loadOAuthStatus();
        const grok = state.oauth?.grok_oauth || {};
        if (grok.authenticated) {
          await loadModels();
          return false;
        }
        if (grok?.login?.status === "running") return true;
        await loadModels();
        elements.grokOauthConnect.disabled = false;
        return false;
      },
      {
        initialDelayMs: 2500,
        intervalMs: 3000,
        maxDurationMs: 120000,
        onTimeout: () => {
          elements.grokStatus.textContent = "El inicio de sesión de Grok ha expirado (120 s).";
          elements.grokOauthConnect.disabled = false;
        },
      },
    );
  } catch (error) {
    elements.grokStatus.textContent = error.message;
    elements.grokOauthConnect.disabled = false;
  }
}

elements.grokOauthConnect?.addEventListener("click", startGrokAuth);
elements.grokLogout?.addEventListener("click", () => logoutOAuth("grok", elements.grokStatus, elements.grokLogout));
elements.grokRefresh?.addEventListener("click", async () => {
  try {
    await api("/api/oauth/grok/refresh", { method: "POST", body: JSON.stringify({ provider: "grok_oauth" }) });
    await loadModels();
  } catch (error) {
    elements.grokStatus.textContent = error.message;
  }
});
elements.grokApiToggle?.addEventListener("click", () => {
  if (!elements.grokKeyRow) return;
  elements.grokKeyRow.hidden = !elements.grokKeyRow.hidden;
  if (!elements.grokKeyRow.hidden && elements.grokApiKey) {
    elements.grokApiKey.focus();
  }
});
elements.grokApiSave?.addEventListener("click", async () => {
  const key = elements.grokApiKey?.value?.trim();
  if (!key) {
    elements.grokStatus.textContent = "Introduce una clave válida de xAI (xai-…).";
    return;
  }
  elements.grokApiSave.disabled = true;
  try {
    elements.grokStatus.textContent = "Guardando credencial de Grok…";
    await api("/api/providers/grok/connect", {
      method: "POST",
      body: JSON.stringify({ provider: "grok_api", api_key: key }),
    });
    elements.grokKeyRow.hidden = true;
    if (elements.grokApiKey) elements.grokApiKey.value = "";
    await loadModels();
    await loadOAuthStatus();
  } catch (error) {
    elements.grokStatus.textContent = error.message;
  } finally {
    elements.grokApiSave.disabled = false;
  }
});
elements.nvidiaApiConnect?.addEventListener("click", async () => {
  const connected = state.models.some((item) => item.provider === "nvidia_api" && item.auth_status === "autenticado");
  if (connected) {
    elements.nvidiaApiRefresh?.click();
    return;
  }
  elements.nvidiaApiKeyRow.hidden = false;
  elements.nvidiaApiKey.focus();
});

elements.nvidiaApiSave?.addEventListener("click", async () => {
  const apiKey = elements.nvidiaApiKey.value.trim();
  if (!apiKey) {
    elements.nvidiaApiStatus.textContent = "Introduce la clave personal de NVIDIA.";
    return;
  }
  elements.nvidiaApiSave.disabled = true;
  elements.nvidiaApiStatus.textContent = "Validando la clave con NVIDIA…";
  try {
    await api("/api/providers/nvidia/connect", {
      method: "POST",
      body: JSON.stringify({ provider: "nvidia_api", api_key: apiKey }),
    });
    elements.nvidiaApiKey.value = "";
    elements.nvidiaApiKeyRow.hidden = true;
    await loadModels();
  } catch (error) {
    elements.nvidiaApiStatus.textContent = error.message;
  } finally {
    elements.nvidiaApiSave.disabled = false;
  }
});

elements.nvidiaApiLogout?.addEventListener("click", async () => {
  if (!window.confirm("¿Desconectar NVIDIA de MyKOS?")) return;
  elements.nvidiaApiLogout.disabled = true;
  try {
    await api("/api/providers/nvidia/logout", { method: "POST", body: JSON.stringify({ provider: "nvidia_api" }) });
    await loadModels();
  } catch (error) {
    elements.nvidiaApiStatus.textContent = error.message;
    elements.nvidiaApiLogout.disabled = false;
  }
});

elements.nvidiaApiRefresh?.addEventListener("click", async () => {
  elements.nvidiaApiRefresh.disabled = true;
  try {
    await api("/api/providers/nvidia/refresh", { method: "POST", body: JSON.stringify({ provider: "nvidia_api" }) });
    await loadModels();
  } catch (error) {
    elements.nvidiaApiStatus.textContent = error.message;
  } finally {
    elements.nvidiaApiRefresh.disabled = false;
  }
});

elements.kimiApiConnect?.addEventListener("click", () => {
  const connected = state.models.some((item) => item.provider === "kimi_api" && item.auth_status === "autenticado");
  if (connected) return elements.kimiApiRefresh?.click();
  elements.kimiApiKeyRow.hidden = false;
  elements.kimiApiKey.focus();
});
elements.kimiApiSave?.addEventListener("click", async () => {
  const apiKey = elements.kimiApiKey.value.trim();
  if (!apiKey) { elements.kimiApiStatus.textContent = "Introduce la clave personal de Kimi."; return; }
  elements.kimiApiSave.disabled = true;
  elements.kimiApiStatus.textContent = "Validando la clave con Kimi…";
  try {
    await api("/api/providers/kimi/connect", { method: "POST", body: JSON.stringify({ provider: "kimi_api", api_key: apiKey }) });
    elements.kimiApiKey.value = ""; elements.kimiApiKeyRow.hidden = true; await loadModels();
  } catch (error) { elements.kimiApiStatus.textContent = error.message; }
  finally { elements.kimiApiSave.disabled = false; }
});
elements.kimiApiLogout?.addEventListener("click", async () => {
  if (!window.confirm("¿Desconectar Kimi de MyKOS?")) return;
  try { await api("/api/providers/kimi/logout", { method: "POST", body: JSON.stringify({ provider: "kimi_api" }) }); await loadModels(); }
  catch (error) { elements.kimiApiStatus.textContent = error.message; }
});
elements.kimiApiRefresh?.addEventListener("click", async () => {
  elements.kimiApiRefresh.disabled = true;
  try { await api("/api/providers/kimi/refresh", { method: "POST", body: JSON.stringify({ provider: "kimi_api" }) }); await loadModels(); }
  catch (error) { elements.kimiApiStatus.textContent = error.message; }
  finally { elements.kimiApiRefresh.disabled = false; }
});

elements.geminiApiConnect?.addEventListener("click", () => {
  const connected = state.models.some((item) => item.provider === "gemini_api" && item.auth_status === "autenticado");
  if (connected) return elements.geminiApiRefresh?.click();
  elements.geminiApiKeyRow.hidden = false;
  elements.geminiApiKey.focus();
});
elements.geminiApiSave?.addEventListener("click", async () => {
  const apiKey = elements.geminiApiKey.value.trim();
  if (!apiKey) { elements.geminiApiStatus.textContent = "Introduce la clave de Google AI Studio."; return; }
  elements.geminiApiSave.disabled = true;
  elements.geminiApiStatus.textContent = "Validando la clave con Google AI Studio…";
  try {
    await api("/api/providers/gemini/connect", { method: "POST", body: JSON.stringify({ provider: "gemini_api", api_key: apiKey }) });
    elements.geminiApiKey.value = ""; elements.geminiApiKeyRow.hidden = true; await loadModels();
  } catch (error) { elements.geminiApiStatus.textContent = error.message; }
  finally { elements.geminiApiSave.disabled = false; }
});
elements.geminiApiLogout?.addEventListener("click", async () => {
  if (!window.confirm("¿Desconectar Gemini de MyKOS?")) return;
  try { await api("/api/providers/gemini/logout", { method: "POST", body: JSON.stringify({ provider: "gemini_api" }) }); await loadModels(); }
  catch (error) { elements.geminiApiStatus.textContent = error.message; }
});
elements.geminiApiRefresh?.addEventListener("click", async () => {
  elements.geminiApiRefresh.disabled = true;
  try { await api("/api/providers/gemini/refresh", { method: "POST", body: JSON.stringify({ provider: "gemini_api" }) }); await loadModels(); }
  catch (error) { elements.geminiApiStatus.textContent = error.message; }
  finally { elements.geminiApiRefresh.disabled = false; }
});

elements.mistralApiConnect?.addEventListener("click", () => {
  const connected = state.models.some((item) => item.provider === "mistral_api" && item.auth_status === "autenticado");
  if (connected) return elements.mistralApiRefresh?.click();
  elements.mistralApiKeyRow.hidden = false;
  elements.mistralApiKey.focus();
});
elements.mistralApiSave?.addEventListener("click", async () => {
  const apiKey = elements.mistralApiKey.value.trim();
  if (!apiKey) {
    elements.mistralApiStatus.textContent = "Introduce la clave personal de Mistral.";
    return;
  }
  elements.mistralApiSave.disabled = true;
  elements.mistralApiStatus.textContent = "Validando la clave con Mistral…";
  try {
    await api("/api/providers/mistral/connect", {
      method: "POST",
      body: JSON.stringify({ provider: "mistral_api", api_key: apiKey }),
    });
    elements.mistralApiKey.value = "";
    elements.mistralApiKeyRow.hidden = true;
    await loadModels();
  } catch (error) {
    elements.mistralApiStatus.textContent = error.message;
  } finally {
    elements.mistralApiSave.disabled = false;
  }
});
elements.mistralApiVibe?.addEventListener("click", async () => {
  elements.mistralApiVibe.disabled = true;
  elements.mistralApiStatus.textContent = "Buscando credenciales en el keyring de Vibe…";
  try {
    await api("/api/providers/mistral/connect", {
      method: "POST",
      body: JSON.stringify({ provider: "mistral_api", link_vibe: true }),
    });
    await loadModels();
  } catch (error) {
    elements.mistralApiStatus.textContent = error.message;
  } finally {
    elements.mistralApiVibe.disabled = false;
  }
});
elements.mistralApiLogout?.addEventListener("click", async () => {
  if (!window.confirm("¿Desconectar Mistral de MyKOS?")) return;
  elements.mistralApiLogout.disabled = true;
  try {
    await api("/api/providers/mistral/logout", { method: "POST", body: JSON.stringify({ provider: "mistral_api" }) });
    await loadModels();
  } catch (error) {
    elements.mistralApiStatus.textContent = error.message;
  } finally {
    elements.mistralApiLogout.disabled = false;
  }
});
elements.mistralApiRefresh?.addEventListener("click", async () => {
  elements.mistralApiRefresh.disabled = true;
  try {
    await api("/api/providers/mistral/refresh", { method: "POST", body: JSON.stringify({ provider: "mistral_api" }) });
    await loadModels();
  } catch (error) {
    elements.mistralApiStatus.textContent = error.message;
  } finally {
    elements.mistralApiRefresh.disabled = false;
  }
});

elements.antigravityCliToggle?.addEventListener("click", async () => {
  const enabled = isAntigravityEnabled();
  elements.antigravityCliToggle.disabled = true;
  try {
    const action = enabled ? "logout" : "connect";
    await api(`/api/providers/antigravity/${action}`, {
      method: "POST",
      body: JSON.stringify({ provider: "antigravity_cli" }),
    });
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    elements.antigravityCliStatus.textContent = error.message;
  } finally {
    elements.antigravityCliToggle.disabled = false;
  }
});
elements.antigravityCliRefresh?.addEventListener("click", async () => {
  elements.antigravityCliRefresh.disabled = true;
  try {
    await api("/api/providers/antigravity/refresh", { method: "POST", body: JSON.stringify({ provider: "antigravity_cli" }) });
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    elements.antigravityCliStatus.textContent = error.message;
  } finally {
    elements.antigravityCliRefresh.disabled = false;
  }
});

elements.qwenCliToggle?.addEventListener("click", async () => {
  const enabled = isQwenCliEnabled();
  elements.qwenCliToggle.disabled = true;
  try {
    const action = enabled ? "logout" : "connect";
    await api(`/api/providers/qwen/${action}`, {
      method: "POST",
      body: JSON.stringify({ provider: "qwen_cli" }),
    });
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    elements.qwenCliStatus.textContent = error.message;
  } finally {
    elements.qwenCliToggle.disabled = false;
  }
});
elements.qwenCliRefresh?.addEventListener("click", async () => {
  elements.qwenCliRefresh.disabled = true;
  try {
    await api("/api/providers/qwen/refresh", { method: "POST", body: JSON.stringify({ provider: "qwen_cli" }) });
    await Promise.all([loadModels(), loadOAuthStatus()]);
  } catch (error) {
    elements.qwenCliStatus.textContent = error.message;
  } finally {
    elements.qwenCliRefresh.disabled = false;
  }
});

async function loadModels() {
  try {
    const data = await api("/api/status");
    state.models = data.models || [];
    state.engines = data.engines || null;
    state.allowedRoots = data.allowed_roots || [];
    state.benchmarkProfiles = data.benchmark_profiles || [];
    elements.model.replaceChildren();
    if (!state.models.length) {
      const option = document.createElement("option");
      option.textContent = "Sin modelos instalados";
      option.value = "";
      elements.model.appendChild(option);
      elements.model.disabled = true;
    } else {
      const groupedModels = new Map();
      const selectableModels = state.models.filter((item) => item.chat_capable !== false);
      for (const model of selectableModels) {
        const provider = model.provider || "other";
        if (!groupedModels.has(provider)) groupedModels.set(provider, []);
        groupedModels.get(provider).push(model);
      }
      for (const [provider, models] of groupedModels) {
        if (!models.length) continue;
        const group = document.createElement("optgroup");
        group.label = `──── ${providerLabel(provider, models)} ────`;
        for (const model of models) {
          const option = document.createElement("option");
          option.value = model.name;
          option.textContent = `${model.label || model.name}${model.provider === "anthropic_oauth" ? " · OAuth" : model.remote ? " · remoto" : ""}${model.vision_capable ? " · visión" : ""}`;
          group.appendChild(option);
        }
        elements.model.appendChild(group);
      }
      elements.model.disabled = false;
      const savedModel = localStorage.getItem("mykos-model");
      const firstUsable = state.models.find((item) => item.chat_capable && !item.remote)
        || state.models.find((item) => item.chat_capable);
      const initialModel = state.models.find((item) => item.name === savedModel && item.chat_capable)
        || state.models.find((item) => item.name === data.default_model && item.chat_capable)
        || firstUsable;
      if (initialModel) elements.model.value = initialModel.name;
    }
    setConnection(true, `MyKOS conectado · ${state.models.length} modelo${state.models.length === 1 ? "" : "s"}`);
    renderOllamaInstalled();
    renderLibraryRoots();
    const toolCount = (data.tools || []).length;
    const rootCount = (data.allowed_roots || []).length;
    const memoryCount = data.memory?.count || 0;
    elements.toolsMeta.textContent = toolCount
      ? `${toolCount} herramientas · ${rootCount} raíces · acciones sensibles con aprobación`
      : "Sin herramientas activas";
    elements.memoryMeta.textContent = `${memoryCount} recuerdo${memoryCount === 1 ? "" : "s"} persistente${memoryCount === 1 ? "" : "s"}`;
    updateModelMeta();
    if (typeof renderSwarmModelOptions === "function") renderSwarmModelOptions();
    syncModelGenerationControls();
    updateLocalEnginesStatus();
    renderBenchmarkResults();
    renderNvidiaApiStatus();
    renderKimiApiStatus();
    renderGeminiApiStatus();
    renderMistralApiStatus();
    renderAntigravityCliStatus();
    renderQwenCliStatus();
    await loadContextMeter();
    await loadOAuthStatus();
  } catch (error) {
    state.models = [];
    elements.model.replaceChildren();
    const option = document.createElement("option");
    option.textContent = "Ollama no disponible";
    elements.model.appendChild(option);
    elements.model.disabled = true;
    elements.modelMeta.textContent = error.message;
    elements.toolsMeta.textContent = "Herramientas no disponibles";
    elements.memoryMeta.textContent = "Memoria no disponible";
    setConnection(false, "MyKOS no disponible");
    await loadOAuthStatus();
  }
}

async function loadConversation() {
  if (!state.conversationId) {
    showWelcome();
    await loadContextMeter();
    return;
  }
  try {
    const data = await api(`/api/conversation?id=${encodeURIComponent(state.conversationId)}`);
    elements.messages.replaceChildren();
    for (const message of data.conversation.messages || []) {
      addBubble(message.role, message.content, false, message.sources || [], message.created_at || "", message.message_id || "", message.model || "", "", message.telemetry || null);
    }
    if (!data.conversation.messages.length) showWelcome();
    await loadContextMeter();
  } catch (_error) {
    state.conversationId = "";
    localStorage.removeItem("mykos-conversation");
    showWelcome();
    await loadContextMeter();
  }
}

async function deleteMessage(messageId) {
  if (!state.conversationId || !messageId) return;
  if (!window.confirm("¿Eliminar este mensaje tuyo de la conversación? Esta acción no borra las respuestas de MyKOS.")) return;
  try {
    const query = new URLSearchParams({ conversation_id: state.conversationId, message_id: messageId });
    await api(`/api/conversations/messages?${query.toString()}`, { method: "DELETE" });
    await loadConversation();
    await loadConversations();
    await loadContextMeter();
  } catch (error) {
    addBubble("assistant", error.message, true);
  }
}

async function loadConversations() {
  try {
    const data = await api("/api/conversations");
    state.conversations = data.conversations || [];
    renderConversationList();
  } catch (error) {
    state.conversations = [];
    renderConversationList();
    elements.conversationList.replaceChildren();
    const failure = document.createElement("div");
    failure.className = "conversation-empty error-text";
    failure.textContent = error.message;
    elements.conversationList.appendChild(failure);
  }
}

function permissionModeLabel(mode) {
  return { once: "Una vez", session: "Sesión", permanent: "Permanente" }[mode] || mode || "—";
}

function renderPermissions(data = {}) {
  const permissions = Array.isArray(data.permissions) ? data.permissions : [];
  const audit = Array.isArray(data.audit) ? data.audit : [];
  elements.permissionsList.replaceChildren();
  elements.auditList.replaceChildren();
  elements.permissionsStatus.textContent = permissions.length
    ? `${permissions.length} permiso${permissions.length === 1 ? "" : "s"} activo${permissions.length === 1 ? "" : "s"}.`
    : "No hay permisos persistentes concedidos.";

  if (permissions.length) {
    for (const permission of permissions) {
      const card = document.createElement("article");
      card.className = "permission-card";
      const title = document.createElement("strong");
      title.textContent = permission.summary || permission.operation || "Permiso";
      const meta = document.createElement("div");
      meta.className = "permission-meta";
      meta.textContent = `${permissionModeLabel(permission.mode)} · ${permission.category || "acción"} · concedido ${permission.created_at || ""}`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "permission-revoke";
      button.textContent = "Revocar";
      button.addEventListener("click", () => revokePermission(permission.id));
      card.append(title, meta, button);
      elements.permissionsList.appendChild(card);
    }
  }

  if (!audit.length) {
    const empty = document.createElement("div");
    empty.className = "panel-help";
    empty.textContent = "Todavía no hay acciones registradas.";
    elements.auditList.appendChild(empty);
  } else {
    for (const entry of audit) {
      const row = document.createElement("div");
      row.className = "audit-row";
      const title = document.createElement("strong");
      title.textContent = `${entry.event || "acción"} · ${entry.summary || entry.operation || ""}`;
      const meta = document.createElement("span");
      meta.textContent = `${entry.at || ""} · ${entry.status || ""} · ${permissionModeLabel(entry.mode)}`;
      row.append(title, meta);
      elements.auditList.appendChild(row);
    }
  }
}

let voiceModeBusy = false;

function renderVoiceMode(data) {
  const mode = ["local", "cloud", "gemini"].includes(data?.mode) ? data.mode : "local";
  const cloudAvailable = Boolean(data?.cloud?.available);
  const geminiAvailable = Boolean(data?.gemini?.available);
  elements.voiceModeLocalButton?.setAttribute("aria-pressed", String(mode === "local"));
  elements.voiceModeCloudButton?.setAttribute("aria-pressed", String(mode === "cloud"));
  elements.voiceModeGeminiButton?.setAttribute("aria-pressed", String(mode === "gemini"));
  if (elements.voiceModeLocalButton) elements.voiceModeLocalButton.disabled = voiceModeBusy;
  if (elements.voiceModeCloudButton) elements.voiceModeCloudButton.disabled = voiceModeBusy;
  if (elements.voiceModeGeminiButton) elements.voiceModeGeminiButton.disabled = voiceModeBusy;
  if (mode === "cloud") {
    elements.voiceModeStatus.textContent = `Llamando por la nube (${data?.cloud?.model || "Realtime"}, voz ${data?.cloud?.voice || "—"}).`;
    elements.voiceModeDetail.textContent = cloudAvailable
      ? "La nube está lista: tiene credencial propia de MyKOS."
      : "La nube no está disponible: falta la credencial propia de MyKOS (mykos realtime set-key).";
  } else if (mode === "gemini") {
    elements.voiceModeStatus.textContent = `Llamando por Gemini Live (${data?.gemini?.model || "Gemini Live"}, voz ${data?.gemini?.voice || "—"}).`;
    elements.voiceModeDetail.textContent = geminiAvailable
      ? "Gemini Live está listo. Al llamar, MyKOS entrega al navegador un token efímero de un solo uso; la API key se queda en MyKOS."
      : (data?.gemini?.error || "Gemini Live no tiene una credencial disponible en MyKOS.");
  } else {
    elements.voiceModeStatus.textContent = "Llamando con el motor local.";
    elements.voiceModeDetail.textContent = "Whisper, modelo y voz en este equipo. Sin coste ni límite de cuota.";
  }
}

async function loadVoiceMode() {
  try {
    const data = await api("/api/voice/mode");
    renderVoiceMode(data);
  } catch (error) {
    elements.voiceModeStatus.textContent = error.message;
  }
}

async function setVoiceMode(mode) {
  if (voiceModeBusy) return;
  voiceModeBusy = true;
  if (elements.voiceModeLocalButton) elements.voiceModeLocalButton.disabled = true;
  if (elements.voiceModeCloudButton) elements.voiceModeCloudButton.disabled = true;
  if (elements.voiceModeGeminiButton) elements.voiceModeGeminiButton.disabled = true;
  elements.voiceModeStatus.textContent = "Cambiando…";
  try {
    const data = await api("/api/voice/mode", { method: "POST", body: JSON.stringify({ mode }) });
    voiceModeBusy = false;
    renderVoiceMode(data);
    if (data.persisted === false) {
      elements.voiceModeDetail.textContent += " Aviso: el cambio es solo para esta sesión del Gateway; no se pudo guardar en disco.";
    }
  } catch (error) {
    voiceModeBusy = false;
    await loadVoiceMode();
    elements.voiceModeDetail.textContent = error.message || "No se pudo cambiar el modo de llamada.";
  }
}

async function loadPermissions() {
  try {
    const query = encodeURIComponent(state.conversationId || "");
    const [permissions, audit] = await Promise.all([
      api(`/api/permissions?conversation_id=${query}`),
      api(`/api/audit?conversation_id=${query}&limit=100`),
    ]);
    renderPermissions({ permissions: permissions.permissions || [], audit: audit.audit || [] });
  } catch (error) {
    elements.permissionsStatus.textContent = error.message;
  }
}

async function revokePermission(permissionId) {
  try {
    await api(`/api/permissions/${encodeURIComponent(permissionId)}/revoke`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadPermissions();
  } catch (error) {
    addBubble("assistant", error.message, true);
  }
}

function renderApprovals() {
  elements.approvalsPanel.replaceChildren();
  if (!state.pendingApprovals.length) {
    elements.approvalsPanel.hidden = true;
    return;
  }

  elements.approvalsPanel.hidden = false;
  const heading = document.createElement("div");
  heading.className = "approvals-heading";
  heading.textContent = "Acciones pendientes de aprobación";
  elements.approvalsPanel.appendChild(heading);

  for (const approval of state.pendingApprovals) {
    const card = document.createElement("article");
    card.className = "approval-card";

    const title = document.createElement("strong");
    title.textContent = approval.title || "Acción pendiente";
    card.appendChild(title);

    if (approval.risk_level === "critical") {
      const banner = document.createElement("div");
      banner.className = "approval-risk-badge critical";
      banner.textContent = `🛑 RIESGO ALTO: ${approval.risk_warning || "Acción potencialmente destructiva o con privilegios"}`;
      card.appendChild(banner);
    } else if (approval.risk_level === "warning") {
      const banner = document.createElement("div");
      banner.className = "approval-risk-badge warning";
      banner.textContent = `⚠️ AVISO: ${approval.risk_warning || "Operación con impacto en infraestructura"}`;
      card.appendChild(banner);
    }

    const target = document.createElement("div");
    target.className = "approval-target";
    if (approval.kind === "write_file") {
      target.textContent = `Archivo: ${approval.root} / ${approval.path}${approval.overwrite ? " · sobrescribir" : " · crear"}`;
    } else if (approval.kind === "edit_file") {
      target.textContent = `Archivo: ${approval.root} / ${approval.path} · editar`;
    } else if (approval.kind === "research_note") {
      target.textContent = `Ficha: ${approval.research_title || "sin título"} · ${approval.root} / ${approval.path} · ${approval.sources_count || 0} fuentes`;
    } else if (approval.kind === "run_powershell") {
      target.textContent = `Directorio: ${approval.cwd_root} / ${approval.cwd_path || "."} · máximo ${approval.timeout_seconds}s`;
    } else if (approval.kind === "save_memory") {
      const tags = (approval.tags || []).join(", ");
      target.textContent = `Memoria: ${approval.memory_title} · ${approval.category}${tags ? ` · ${tags}` : ""}${approval.memory_id ? " · actualizar" : " · nueva"}`;
    } else if (approval.kind === "delete_memory") {
      target.textContent = `Recuerdo: ${approval.memory_title} · ${approval.category} · ${approval.memory_id}`;
    } else if (approval.kind === "stop_process") {
      target.textContent = `Proceso: ${approval.process_name || "desconocido"} · PID ${approval.pid}${approval.memory_bytes ? ` · ${formatBytes(approval.memory_bytes)}` : ""}`;
    } else if (["start_service", "stop_service"].includes(approval.kind)) {
      target.textContent = `Servicio: ${approval.service} · ${approval.display_name || "sin nombre visible"}`;
    } else if (approval.kind === "git_commit") {
      const scope = approval.paths?.length
        ? approval.paths.join(", ")
        : approval.stage_all
          ? "todos los cambios actuales"
          : "solo cambios ya preparados";
      target.textContent = `Repositorio: ${approval.root} · ${approval.stage_mode || scope}`;
    } else if (approval.kind === "git_branch") {
      target.textContent = `Repositorio: ${approval.root} · rama ${approval.branch} (${approval.operation === "switch" ? "cambiar" : "crear"})`;
    } else if (["git_remote_fetch", "git_remote_pull", "git_remote_push"].includes(approval.kind)) {
      target.textContent = `Repositorio: ${approval.root} · remoto ${approval.remote || "origin"}${approval.branch ? ` / ${approval.branch}` : ""}`;
    } else if (approval.kind === "pull_ollama_model") {
      target.textContent = `Ollama: ${approval.model} · ${approval.already_installed ? "actualizar instalado" : "descargar nuevo"}`;
    } else if (approval.kind === "delete_ollama_model") {
      target.textContent = `Ollama: ${approval.model} · eliminar${approval.size ? ` · ${formatBytes(approval.size)}` : ""}`;
    } else if (approval.kind === "create_reminder") {
      const repeat = approval.repeat_minutes ? `cada ${approval.repeat_minutes} min` : "una vez";
      target.textContent = `Recordatorio nuevo: ${approval.title || "sin título"} · ${repeat}`;
    } else if (approval.kind === "delete_reminder") {
      target.textContent = `Recordatorio: ${approval.target_id || "sin identificador"}`;
    } else if (approval.kind === "spawn_subagent") {
      target.textContent = `Subagente: ${approval.title || "Subagente local"} · modelo ${approval.model || "por defecto"}`;
    } else if (approval.kind === "text_to_speech") {
      target.textContent = `Síntesis de voz: ${approval.voice || "voz por defecto"} · ${approval.filename || "audio.wav"}`;
    } else if (approval.kind === "generate_image") {
      const modelTag = approval.model ? ` · ${approval.model}` : " · flux";
      target.textContent = `Generar imagen con Pollinations.ai (${approval.aspect_ratio || "1:1"}${modelTag}): ${approval.prompt || "sin descripción"}`;
    } else if (approval.kind === "generate_video") {
      const motionTag = approval.motion ? ` · ${approval.motion}` : " · cinemático";
      target.textContent = `Generar vídeo con Pollinations.ai (${approval.aspect_ratio || "1:1"}${motionTag}): ${approval.prompt || "sin descripción"}`;
    } else if (approval.kind === "pair_node") {
      target.textContent = `Emparejar nodo: ${approval.name || "sin nombre"} (${approval.node_kind || "node"})`;
    } else if (approval.kind === "revoke_node") {
      target.textContent = `Revocar nodo: ${approval.node_id || ""}`;
    } else {
      target.textContent = "Acción no reconocida";
    }
    card.appendChild(target);

    const preview = document.createElement("pre");
    preview.className = "approval-preview";
    if (["write_file", "research_note", "save_memory"].includes(approval.kind)) {
      preview.textContent = `${approval.content_preview || ""}${approval.content_truncated ? "\n… contenido recortado para la vista previa …" : ""}`;
    } else if (approval.kind === "edit_file") {
      preview.textContent = `${approval.content_preview || approval.summary || approval.preview_row || ""}${approval.content_truncated ? "\n… contenido recortado para la vista previa …" : ""}`;
    } else if (approval.kind === "run_powershell") {
      preview.textContent = approval.command || "";
    } else if (approval.kind === "stop_process") {
      preview.textContent = `Se solicitará detener el proceso ${approval.process_name} (PID ${approval.pid}).\nEstado revisado: ${approval.status || "desconocido"}.\nIdentidad comprobada: ${approval.created_at_process || "no disponible"}.`;
    } else if (["start_service", "stop_service"].includes(approval.kind)) {
      const action = approval.kind === "start_service" ? "iniciará" : "detendrá";
      preview.textContent = `Se ${action} el servicio ${approval.service}.\nEstado revisado: ${approval.status || "desconocido"}.\nTipo de inicio: ${approval.start_type || "desconocido"}.`;
    } else if (approval.kind === "git_commit") {
      const parts = [`Mensaje: ${approval.message || ""}`];
      if (approval.status_preview) parts.push(`Estado revisado:\n${approval.status_preview}`);
      if (approval.staged_stat) parts.push(`Cambios preparados:\n${approval.staged_stat}`);
      if (approval.unstaged_stat) parts.push(`Cambios sin preparar:\n${approval.unstaged_stat}`);
      if (approval.status_truncated) parts.push("… estado recortado para la vista previa …");
      preview.textContent = parts.join("\n\n");
    } else if (approval.kind === "git_branch") {
      preview.textContent = `Operación: ${approval.operation}\nRama: ${approval.branch}${approval.start_point ? `\nDesde: ${approval.start_point}` : ""}`;
    } else if (["git_remote_fetch", "git_remote_pull", "git_remote_push"].includes(approval.kind)) {
      const parts = [`Remoto: ${approval.remote || "origin"}${approval.remote_url ? ` (${approval.remote_url})` : ""}`];
      if (approval.branch) parts.push(`Rama: ${approval.branch}`);
      if (approval.kind === "git_remote_pull") parts.push("Modo: fast-forward (--ff-only)");
      if (approval.kind === "git_remote_push" && approval.set_upstream) parts.push("Con --set-upstream");
      preview.textContent = parts.join("\n");
    } else if (approval.kind === "pull_ollama_model") {
      preview.textContent = approval.already_installed
        ? "Se actualizará el modelo ya instalado. La descarga puede tardar y consumir red y disco."
        : "Se descargará el modelo desde la instancia configurada de Ollama. Puede consumir red y bastante espacio en disco.";
    } else if (approval.kind === "delete_ollama_model") {
      preview.textContent = `Se eliminará definitivamente el modelo ${approval.model}. Esta acción libera espacio y no se puede deshacer sin volver a descargarlo.`;
    } else if (approval.kind === "create_reminder") {
      preview.textContent = `Se activará: ${formatAutomationDate(approval.run_at)}\n${approval.message || "(sin mensaje adicional)"}`;
    } else if (approval.kind === "delete_reminder") {
      preview.textContent = "Se eliminará este recordatorio programado. No se puede deshacer.";
    } else if (approval.kind === "spawn_subagent") {
      preview.textContent = approval.prompt || "";
    } else if (approval.kind === "text_to_speech") {
      preview.textContent = approval.text || "";
    } else if (approval.kind === "generate_image") {
      preview.textContent = `⚠️ Servicio externo en la nube: se enviará la descripción en texto a Pollinations.ai (FLUX) para generar la imagen.\n\nDescripción: ${approval.prompt || ""}`;
    } else if (approval.kind === "generate_video") {
      preview.textContent = `⚠️ Servicio externo en la nube: se enviará la descripción en texto a Pollinations.ai (FLUX Motion) para generar el vídeo.\n\nDescripción: ${approval.prompt || ""}`;
    } else if (approval.kind === "pair_node") {
      preview.textContent = `Capacidades: ${(approval.capabilities || []).join(", ") || "ninguna"}`;
    } else if (approval.kind === "revoke_node") {
      preview.textContent = "Se revocará el acceso del nodo emparejado.";
    } else {
      preview.textContent = "";
    }
    card.appendChild(preview);

    const expiry = document.createElement("div");
    expiry.className = "approval-expiry";
    expiry.textContent = `Caduca: ${approval.expires_at || "en breve"}`;
    card.appendChild(expiry);

    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const approvalBusy = state.approvalBusy.has(approval.id);
    const modes = Array.isArray(approval.permission?.modes) && approval.permission.modes.length
      ? approval.permission.modes
      : [{ id: "once", label: "Una vez" }];
    for (const mode of modes) {
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = mode.id === "permanent" ? "approval-approve approval-permanent" : "approval-approve";
      approve.disabled = approvalBusy;
      approve.title = mode.description || "";
      approve.textContent = approvalBusy ? "Procesando…" : `Aprobar · ${mode.label}`;
      approve.addEventListener("click", () => decideApproval(approval.id, "approve", mode.id));
      actions.appendChild(approve);
    }
    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "approval-reject";
    reject.disabled = approvalBusy;
    reject.textContent = approvalBusy ? "Espera…" : "Rechazar";
    reject.addEventListener("click", () => decideApproval(approval.id, "reject", "once"));
    actions.appendChild(reject);
    card.appendChild(actions);
    elements.approvalsPanel.appendChild(card);
  }
}

async function loadApprovals() {
  if (!state.conversationId) {
    state.pendingApprovals = [];
    renderApprovals();
    return;
  }
  try {
    const data = await api(`/api/approvals?conversation_id=${encodeURIComponent(state.conversationId)}`);
    state.pendingApprovals = data.approvals || [];
  } catch (_error) {
    state.pendingApprovals = [];
  }
  renderApprovals();
}

async function decideApproval(approvalId, decision, permissionMode = "once") {
  if (state.approvalBusy.has(approvalId)) return;
  state.approvalBusy.add(approvalId);
  renderApprovals();
  state.busy = true;
  elements.send.disabled = true;
  const activityId = beginActivity();
  let waitingForApproval = false;
  try {
    const data = await api(`/api/approvals/${encodeURIComponent(approvalId)}/${decision}`, {
      method: "POST",
      body: JSON.stringify({
        activity_id: activityId,
        permission_mode: permissionMode,
        conversation_permission_mode: document.getElementById("permission-mode-select")?.value || "supervisado",
      }),
    });
    waitingForApproval = Boolean(data.needs_approval);
    if (data.message?.content) {
      const usage = data.usage || {};
      const tokens = Number(usage.total_tokens || 0);
      const seconds = Number(data.duration_seconds || 0);
      const meta = [seconds > 0 ? `${seconds.toFixed(1)} s` : "", tokens > 0 ? `${tokens.toLocaleString("es-ES")} tokens` : ""].filter(Boolean).join(" · ");
      addBubble("assistant", data.message.content, false, data.message.sources || [], data.message.created_at || "", "", data.message.model || data.model || "", meta, data.message.telemetry || data.telemetry || null);
    }
    if (data.context) {
      state.context = data.context;
      renderContextMeter(state.context);
    }
    if (data.job) rememberOllamaJob(data.job);
    if (decision === "reject") {
      addBubble("assistant", "Solicitud rechazada. No se ha realizado ninguna acción.");
    }
    await loadConversations(); await loadConversation(); await loadApprovals();
    await loadPermissions();
    await loadContextMeter();
  } catch (error) {
    addBubble("assistant", error.message, true);
    endActivity(error.message);
    await loadApprovals();
  } finally {
    if (state.activityId) endActivity("", waitingForApproval);
    state.busy = false;
    state.approvalBusy.delete(approvalId);
    renderApprovals();
    elements.send.disabled = state.busy;
    elements.input.focus();
  }
}

async function openConversation(conversationId) {
  if (state.localVoiceCall && state.conversationId && state.conversationId !== conversationId) {
    await endLocalVoiceCall();
  }
  state.conversationId = conversationId;
  localStorage.setItem("mykos-conversation", conversationId);
  renderConversationList();
  await loadConversation();
  await loadApprovals();
  await loadPermissions();
}

async function deleteConversation(conversationId) {
  const conversation = state.conversations.find((item) => item.id === conversationId);
  const title = conversation?.title || "esta conversación";
  if (!window.confirm(`¿Eliminar definitivamente «${title}»? Esta acción también la borrará del archivo local.`)) {
    return;
  }
  try {
    await api(`/api/conversations?id=${encodeURIComponent(conversationId)}`, { method: "DELETE" });
    if (state.conversationId === conversationId) {
      state.conversationId = "";
      localStorage.removeItem("mykos-conversation");
      showWelcome();
      await loadContextMeter();
    }
    await loadConversations(); await loadConversation(); await loadApprovals();
  } catch (error) {
    addBubble("assistant", error.message, true);
  }
}

async function exportCurrentSession() {
  if (!state.conversationId) {
    addBubble("assistant", "No hay una conversación activa para exportar.", true);
    return;
  }
  window.location.href = `/api/conversations/export?id=${encodeURIComponent(state.conversationId)}`;
}

async function compactCurrentContext() {
  if (!state.conversationId) {
    addBubble("assistant", "No hay una conversación activa para compactar.", true);
    return;
  }
  if (!window.confirm("¿Compactar el contexto? El historial completo seguirá guardado y exportable.")) return;
  try {
    const data = await api("/api/conversations/compact", {
      method: "POST",
      body: JSON.stringify({ conversation_id: state.conversationId }),
    });
    await loadConversation();
    await loadContextMeter();
    elements.contextMeterDetail.textContent = data.detail || "Contexto actualizado.";
  } catch (error) {
    addBubble("assistant", error.message, true);
  }
}

function renderHelp(items) {
  elements.helpList.replaceChildren();
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "help-card";
    const title = document.createElement("strong");
    title.textContent = item.name || "Herramienta";
    const description = document.createElement("p");
    description.textContent = item.description || "";
    const scope = document.createElement("span");
    scope.textContent = item.scope || "";
    card.append(title, description, scope);
    elements.helpList.appendChild(card);
  }
}

async function openHelpPanel() {
  elements.helpPanel.hidden = false;
  if (state.helpLoaded) return;
  try {
    const data = await api("/api/tools");
    renderHelp(data.tools || []);
    state.helpLoaded = true;
  } catch (error) {
    elements.helpList.replaceChildren();
    const failure = document.createElement("div");
    failure.className = "error-text";
    failure.textContent = error.message;
    elements.helpList.appendChild(failure);
  }
}

function closeHelpPanel() {
  elements.helpPanel.hidden = true;
}

async function sendMessage(event) {
  event.preventDefault();
  const message = elements.input.value.trim();
  if ((!message && !state.attachments.length) || state.busy || !selectedModel()) return;
  if (["/help", "/ayuda", "ayuda"].includes(message.toLowerCase()) && !state.attachments.length) {
    elements.input.value = "";
    await openHelpPanel();
    return;
  }
  state.busy = true;
  elements.send.disabled = true;
  const activityId = beginActivity();
  let waitingForApproval = false;
  elements.input.value = "";
  const clientMessageId = window.crypto?.randomUUID?.() || `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const attachmentIds = state.attachments.map((attachment) => attachment.id);
  const attachmentLabel = state.attachments.length
    ? `\n\n[Adjuntos: ${state.attachments.map((attachment) => attachment.name).join(", ")}]`
    : "";
  const sentAt = new Date().toISOString();
  addBubble("user", `${message || "Analiza los archivos adjuntos."}${attachmentLabel}`, false, [], sentAt, clientMessageId);
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: message || "Analiza los archivos adjuntos.",
        attachments: attachmentIds,
        model: selectedModel(),
        generation: currentGeneration(),
        conversation_id: state.conversationId,
        activity_id: activityId,
        client_message_id: clientMessageId,
          permission_mode: document.getElementById("permission-mode-select")?.value || "supervisado",
      }),
    });
    waitingForApproval = Boolean(data.needs_approval);
    state.conversationId = data.conversation_id;
    localStorage.setItem("mykos-conversation", state.conversationId);
    if (data.message?.content) {
      addBubble("assistant", data.message.content, false, data.message.sources || [], data.message.created_at || "", "", data.message.model || data.model || "", "", data.message.telemetry || data.telemetry || null);
    }
    if (data.context) {
      state.context = data.context;
      renderContextMeter(state.context);
    }
    state.attachments = [];
    renderAttachments();
    await loadConversations(); await loadConversation(); await loadApprovals();
    await loadContextMeter();
    if (Array.isArray(data.tools_used) && data.tools_used.some((t) => String(t).startsWith("swarm_"))) {
      loadSwarmStatus({ schedule: true });
    }
  } catch (error) {
    addBubble("assistant", error.message, true);
    endActivity(error.message);
  } finally {
    if (state.activityId) endActivity("", waitingForApproval);
    state.busy = false;
    elements.send.disabled = false;
    elements.input.focus();
  }
}

async function newConversation() {
  try {
    toggleConversationList(true);
    const data = await api("/api/conversations/new", { method: "POST", body: "{}" });
    state.conversationId = data.conversation.id;
    setPage("chat");
    localStorage.setItem("mykos-conversation", state.conversationId);
    showWelcome();
    await loadContextMeter();
    await loadConversations(); await loadConversation(); await loadApprovals();
    elements.input.focus();
  } catch (error) {
    addBubble("assistant", error.message, true);
  }
}

elements.composer.addEventListener("submit", sendMessage);
elements.newChat.addEventListener("click", newConversation);
elements.deleteSession.addEventListener("click", () => {
  if (state.conversationId) deleteConversation(state.conversationId);
});
elements.exportSession.addEventListener("click", exportCurrentSession);
elements.compactContext.addEventListener("click", compactCurrentContext);
elements.helpCommands.addEventListener("click", openHelpPanel);
elements.helpClose.addEventListener("click", closeHelpPanel);
elements.modelsBack.addEventListener("click", () => setPage("chat"));
elements.cortexBack?.addEventListener("click", () => setPage("chat"));
elements.cortexRefresh?.addEventListener("click", () => loadCortexGraph({ fitOnFirst: false }));
elements.cortexFit?.addEventListener("click", () => fitCortexGraph());
elements.permissionsBack.addEventListener("click", () => setPage("chat"));
elements.automationsBack.addEventListener("click", () => setPage("chat"));
elements.automationCreateForm.addEventListener("submit", submitAutomationCreate);
elements.automationEventsClear.addEventListener("click", clearAutomationEvents);
elements.managementRefresh.addEventListener("click", () => loadManagement());
elements.mediaRefresh.addEventListener("click", () => loadMedia());
elements.nodesRefresh.addEventListener("click", () => loadNodes());
for (const item of elements.navItems) item.addEventListener("click", () => setPage(item.dataset.page));
elements.cortexBtn?.addEventListener("click", () => {
  setPage("cortex");
  if (window.innerWidth <= 720) document.querySelector("#sidebar-close")?.click();
});
elements.openSwarmButton?.addEventListener("click", () => {
  setPage("swarm");
  if (window.innerWidth <= 720) document.querySelector("#sidebar-close")?.click();
});
elements.swarmBack?.addEventListener("click", () => setPage("chat"));
elements.settingsNavBtn?.addEventListener("click", () => {
  setPage("settings");
  if (window.innerWidth <= 720) document.querySelector("#sidebar-close")?.click();
});
elements.settingsBack?.addEventListener("click", () => setPage("chat"));
initTheme();
initChatDimensions();
initVoiceSettings();
initSettingsTabs();
initModelsTabs();
initUserProfile();
initSystemUpdates();
mountModelsPage();
mountPermissionsPage();
restoreSidebarState();
updateVoiceModeButton();

// Selector de modo de permisos: recuerda la selección y marca el estilo según el modo activo.
const permissionModeSelect = document.getElementById("permission-mode-select");
const permissionModeSelectLabel = permissionModeSelect?.closest(".permission-mode-label");
function updatePermissionModeStyle() {
  if (!permissionModeSelectLabel) return;
  permissionModeSelectLabel.classList.remove("mode-solo_lectura", "mode-supervisado", "mode-acceso_total");
  permissionModeSelectLabel.classList.add(`mode-${permissionModeSelect.value}`);
}
if (permissionModeSelect) {
  const saved = localStorage.getItem("mykos-permission-mode");
  if (saved && ["solo_lectura", "supervisado", "acceso_total"].includes(saved)) {
    permissionModeSelect.value = saved;
  }
  permissionModeSelect.addEventListener("change", () => {
    localStorage.setItem("mykos-permission-mode", permissionModeSelect.value);
    updatePermissionModeStyle();
  });
  updatePermissionModeStyle();
}
elements.model.addEventListener("change", () => {
  localStorage.setItem("mykos-model", selectedModel());
  updateModelMeta();
  syncModelGenerationControls();
  loadContextMeter();
});
for (const control of [elements.modelEffort, elements.modelSpeed, elements.modelCreativity]) {
  control.addEventListener("change", () => {
    saveCurrentGeneration();
    syncModelGenerationControls();
    loadContextMeter();
  });
}
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

elements.ollamaToggle.addEventListener("click", async () => {
  const opening = elements.ollamaManager.hidden;
  elements.ollamaManager.hidden = !opening;
  elements.ollamaToggle.textContent = opening ? "Cerrar" : "Abrir";
  elements.ollamaToggle.setAttribute("aria-expanded", String(opening));
  if (opening) {
    renderOllamaInstalled();
    if (!state.ollamaCatalog.length) await searchOllamaCatalog();
  }
});
elements.ollamaCatalogForm.addEventListener("submit", (event) => {
  event.preventDefault();
  searchOllamaCatalog();
});
elements.modelTuningToggle.addEventListener("click", () => {
  const opening = elements.modelTuning.hidden;
  elements.modelTuning.hidden = !opening;
  elements.modelTuningToggle.textContent = opening ? "Cerrar" : "Abrir";
  elements.modelTuningToggle.setAttribute("aria-expanded", String(opening));
  if (opening) syncModelGenerationControls();
});
elements.benchmarkToggle.addEventListener("click", () => {
  const opening = elements.benchmarkManager.hidden;
  elements.benchmarkManager.hidden = !opening;
  elements.benchmarkToggle.textContent = opening ? "Cerrar" : "Abrir";
  elements.benchmarkToggle.setAttribute("aria-expanded", String(opening));
  if (opening) renderBenchmarkResults();
});
elements.benchmarkCurrent.addEventListener("click", () => runBenchmarks(false));
elements.benchmarkAll.addEventListener("click", () => runBenchmarks(true));
elements.permissionsToggle.addEventListener("click", async () => {
  const opening = elements.permissionsManager.hidden;
  elements.permissionsManager.hidden = !opening;
  elements.permissionsToggle.textContent = opening ? "Cerrar" : "Abrir";
  elements.permissionsToggle.setAttribute("aria-expanded", String(opening));
  if (opening) await loadPermissions();
});

elements.voiceModeToggle.addEventListener("click", async () => {
  const opening = elements.voiceModeContent.hidden;
  elements.voiceModeContent.hidden = !opening;
  elements.voiceModeToggle.textContent = opening ? "Cerrar" : "Abrir";
  elements.voiceModeToggle.setAttribute("aria-expanded", String(opening));
  if (opening) await loadVoiceMode();
});
elements.voiceModeLocalButton?.addEventListener("click", () => setVoiceMode("local"));
elements.voiceModeCloudButton?.addEventListener("click", () => setVoiceMode("cloud"));
elements.voiceModeGeminiButton?.addEventListener("click", () => setVoiceMode("gemini"));
elements.libraryToggle.addEventListener("click", async () => {
  const opening = elements.libraryManager.hidden;
  elements.libraryManager.hidden = !opening;
  elements.libraryToggle.textContent = opening ? "Cerrar" : "Abrir";
  elements.libraryToggle.setAttribute("aria-expanded", String(opening));
  if (opening) {
    renderLibraryRoots();
    await loadLibraryDirectory(state.libraryPath);
  }
});
elements.libraryRoot.addEventListener("change", () => {
  state.libraryRoot = elements.libraryRoot.value;
  state.libraryPath = ".";
  elements.librarySearchQuery.value = "";
  loadLibraryDirectory(".");
});
elements.libraryOpenPath.addEventListener("click", () => loadLibraryDirectory(elements.libraryPath.value.trim() || "."));
elements.libraryPath.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadLibraryDirectory(elements.libraryPath.value.trim() || ".");
  }
});
elements.librarySearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  searchLibrary();
});
// La interfaz visual de llamada es única. Durante la migración conserva el motor
// local como reserva, pero cuando MyKOS activa Realtime usa WebRTC sin cambiar
// botones, panel ni controles.

async function realtimeEnabledInMyKOS() {
  try {
    const response = await fetch("/mykos-health", { cache: "no-store" });
    const health = await response.json();
    return response.ok && health?.realtime?.enabled === true && health?.realtime?.configured === true;
  } catch { return false; }
}

function waitForIceGathering(peer) {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => { peer.removeEventListener("icegatheringstatechange", done); reject(new Error("No se pudo preparar la conexión de voz.")); }, 10_000);
    function done() {
      if (peer.iceGatheringState !== "complete") return;
      window.clearTimeout(timeout);
      peer.removeEventListener("icegatheringstatechange", done);
      resolve();
    }
    peer.addEventListener("icegatheringstatechange", done);
  });
}

async function saveRealtimeTranscript(role, text, entryId) {
  const callId = state.localVoiceCallId;
  const clean = String(text || "").trim();
  const id = String(entryId || "").trim();
  if (!callId || !clean || !id || state.realtimeTranscriptIds.has(id)) return;
  state.realtimeTranscriptIds.add(id);
  try {
    await api("/api/calls/" + encodeURIComponent(callId) + "/transcript", { method: "POST", body: JSON.stringify({ role, text: clean, entryId: id }) });
    await loadConversations();
    await loadConversation();
  } catch { /* la llamada sigue viva aunque falle la persistencia; el Gateway lo audita */ }
}

// Solo pinta la transcripción en pantalla; la persistencia en la conversación sigue
// pasando por las delegaciones (/api/calls/{id}/turn), así que no se guarda nada aquí.
const REALTIME_TRANSCRIPT_EVENTS = Object.freeze({
  "session.input_transcript.delta": ["user", "delta"],
  "session.output_transcript.delta": ["assistant", "delta"],
  "response.output_audio_transcript.delta": ["assistant", "delta"],
  "response.audio_transcript.delta": ["assistant", "delta"],
  "conversation.item.input_audio_transcription.completed": ["user", "line"],
});
const QUIET_REALTIME_EVENTS = new Set(["session.started", "session.closed", "session.updated", "session.usage.updated", "error", "info", "session.delegation.created", "delegation.created"]);

function handleRealtimeTranscriptEvent(type, event) {
  const spec = REALTIME_TRANSCRIPT_EVENTS[type];
  if (!spec) {
    // Diagnóstico sin contenido: primera aparición de cada tipo de evento no reconocido.
    if (type && !QUIET_REALTIME_EVENTS.has(type) && !state.callEventTypes.has(type)) {
      state.callEventTypes.add(type);
      console.info("[MyKOS Realtime] evento sin tratar", { type, keys: Object.keys(event || {}) });
    }
    return;
  }
  const raw = event?.delta ?? event?.text ?? event?.transcript ?? "";
  const text = typeof raw === "string" ? raw : "";
  if (!text) return;
  if (spec[1] === "delta") state.callTranscript?.appendDelta(spec[0], text);
  else callTranscriptLine(spec[0], text);
}

function handleRealtimeEvent(event) {
  const type = String(event?.type || "");
  if (type === "session.started") setVoiceButton("listening", "Micrófono abierto. Habla con normalidad.");
  if (type === "session.closed") {
    // Diagnóstico: sin audio ni SDP, solo el motivo que envíe el proveedor.
    const reason = String(event?.reason || event?.error?.message || event?.error?.code || event?.code || "").slice(0, 160);
    console.warn("[MyKOS Realtime] session.closed", { at: new Date().toISOString(), reason, keys: Object.keys(event || {}) });
    void finishRealtimeVoiceCall(reason ? `Llamada cerrada por Realtime: ${reason}` : "Llamada cerrada por Realtime (sin motivo)");
  }
  handleRealtimeTranscriptEvent(type, event);
  if (type === "delegation.created" || type === "session.delegation.created") void handleRealtimeDelegation(event);
  if (type === "error") setVoiceButton("listening", String(event?.error?.message || event?.message || "Error temporal de Realtime."));
}

function realtimeDelegationInput(event) {
  const direct = String(event?.prompt || event?.input || "").trim();
  if (direct) return direct;
  const parts = Array.isArray(event?.item?.content) ? event.item.content : [];
  return parts
    .filter((part) => part && (part.type === "input_text" || typeof part.text === "string"))
    .map((part) => String(part.text || "").trim())
    .filter(Boolean)
    .join("\n");
}

function appendRealtimeDelegation(delegationId, text) {
  const channel = state.realtimeChannel;
  const content = String(text || "").trim().slice(0, 1800);
  if (!content || channel?.readyState !== "open" || !state.realtimeVoiceActive) return false;
  try {
    // Contrato GPT-Live/Codex: la capa Live pone la voz; MyKOS devuelve el
    // resultado de su motor, permisos y memoria para que se pronuncie.
    channel.send(JSON.stringify({
      type: "delegation.context.append",
      delegation_item_id: delegationId,
      channel: "speakable",
      content: [{ type: "input_text", text: content }],
    }));
    return true;
  } catch {
    return false;
  }
}

// Texto que se le pasa a la voz de Realtime: sin envoltorio JSON, formato ni símbolos.
// La pantalla y el chat conservan el texto original; esto solo afecta a lo que se pronuncia.
const ANSWER_WRAPPER_KEYS = new Set(["respuesta", "answer", "content", "response", "reply", "texto", "text", "message", "mensaje"]);

function unwrapJsonAnswer(value) {
  let text = String(value ?? "").trim();
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced) text = fenced[1].trim();
  for (let depth = 0; depth < 3; depth += 1) {
    const object = text.startsWith("{") && text.endsWith("}");
    const quoted = text.length > 1 && text.startsWith('"') && text.endsWith('"');
    if (!object && !quoted) break;
    let parsed;
    try { parsed = JSON.parse(text); } catch { break; }
    if (typeof parsed === "string") { text = parsed.trim(); continue; }
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      if (parsed.kind === "tool_call" || parsed.tool_name) {
        text = parsed.content ? String(parsed.content).trim() : "";
        break;
      }
      const keys = Object.keys(parsed);
      if (keys.length === 1 && ANSWER_WRAPPER_KEYS.has(keys[0].toLowerCase()) && typeof parsed[keys[0]] === "string") {
        text = parsed[keys[0]].trim();
        continue;
      }
    }
    break;
  }
  return text;
}

function speakableText(value) {
  const spoken = unwrapJsonAnswer(value)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+|file:\/\/\S+/g, " ")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s*[-*•>]\s+/gm, "")
    .replace(/([^\s.!?…:;,])[ \t]*\n+\s*/g, "$1. ") // un salto de línea se lee como pausa
    .replace(/&/g, " y ")
    .replace(/%/g, " por ciento")
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, " ")
    .replace(/[*_`~^|<>{}\[\]()"“”«»\\\/]/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
  return spoken;
}

async function handleRealtimeDelegation(event) {
  const delegationId = String(event?.item?.id || event?.delegation?.id || event?.id || "").trim();
  if (!delegationId || state.realtimeDelegationIds.has(delegationId)) return;
  state.realtimeDelegationIds.add(delegationId);
  const transcript = realtimeDelegationInput(event);
  if (!transcript) {
    appendRealtimeDelegation(delegationId, "Pide al usuario que repita la petición; no se recibió una transcripción válida.");
    return;
  }
  const callId = state.localVoiceCallId;
  if (!callId) return;
  setVoiceButton("thinking", "MyKOS está procesando tu petición…");
  try {
    const result = await api("/api/calls/" + encodeURIComponent(callId) + "/turn", {
      method: "POST",
      body: JSON.stringify({
        turnId: voiceTurnId(),
        transcript,
        synthesize: false,
        permission_mode: document.getElementById("permission-mode-select")?.value || "supervisado",
      }),
    });
    const answer = String(result.text || "").trim()
      || (result.pending_action ? "He preparado una aprobación para esa acción." : "No he podido preparar una respuesta.");
    appendRealtimeDelegation(delegationId, speakableText(answer) || answer);
    await loadConversations();
    await loadConversation();
    if (result.pending_action) await loadApprovals();
  } catch (error) {
    appendRealtimeDelegation(delegationId, "No he podido completar esa petición ahora mismo. Puedes intentarlo de nuevo.");
    if (state.realtimeVoiceActive) setVoiceButton("listening", error?.message || "Error al procesar la petición.");
  }
}

async function finishRealtimeVoiceCall(detail = "Llamada colgada", { keepPanel = false } = {}) {
  state.realtimeVoiceActive = false;
  state.realtimeChannel?.close();
  state.realtimePeer?.close();
  state.realtimeAudio?.pause();
  state.realtimeAudio?.remove();
  state.realtimeChannel = null;
  state.realtimePeer = null;
  state.realtimeAudio = null;
  state.realtimeTranscriptIds.clear();
  state.realtimeDelegationIds.clear();
  const callId = state.localVoiceCallId;
  state.localVoiceCall = false;
  await releaseVoiceMedia();
  if (callId) { try { await api("/api/calls/" + encodeURIComponent(callId), { method: "DELETE" }); } catch {} }
  state.localVoiceCallId = "";
  setVoiceCallUi(keepPanel);
  if (keepPanel) stopCallVisual();
  if (keepPanel && elements.voiceCallStage) {
    elements.voiceCallStatus.textContent = "No se ha podido conectar";
    elements.voiceCallDetail.textContent = detail;
  }
  setVoiceButton("idle", detail);
}

async function startRealtimeVoiceCall() {
  await ensureVoiceConversation();
  // Conserva la misma pantalla de llamada anterior desde el primer instante:
  // permiso de micrófono, ICE y creación de sesión incluidos.
  state.localVoiceCall = true;
  setVoiceCallUi(true);
  setVoiceButton("connecting", "Abriendo micrófono…");
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
  state.localVoiceStream = stream;
  // Analizadores solo para el visual de la llamada: no cambian el audio ni la conexión.
  try {
    state.callAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    await state.callAudioContext.resume().catch(() => {});
    state.callMicAnalyser = state.callAudioContext.createAnalyser();
    state.callMicAnalyser.fftSize = 1024;
    state.callAudioContext.createMediaStreamSource(stream).connect(state.callMicAnalyser);
  } catch {
    state.callMicAnalyser = null;
  }
  const peer = new RTCPeerConnection();
  state.realtimePeer = peer;
  for (const track of stream.getAudioTracks()) peer.addTrack(track, stream);
  const audio = document.createElement("audio");
  audio.autoplay = true;
  audio.playsInline = true;
  audio.hidden = true;
  document.body.appendChild(audio);
  state.realtimeAudio = audio;
  peer.addEventListener("track", (event) => {
    audio.srcObject = event.streams[0] || new MediaStream([event.track]);
    audio.play().catch(() => {});
    try {
      if (state.callAudioContext && !state.callRemoteAnalyser) {
        state.callRemoteAnalyser = state.callAudioContext.createAnalyser();
        state.callRemoteAnalyser.fftSize = 1024;
        state.callAudioContext.createMediaStreamSource(audio.srcObject).connect(state.callRemoteAnalyser);
      }
    } catch {
      state.callRemoteAnalyser = null;
    }
  });
  peer.addEventListener("connectionstatechange", () => {
    console.warn("[MyKOS Realtime] connectionState", { at: new Date().toISOString(), connection: peer.connectionState, ice: peer.iceConnectionState });
    if (["failed", "closed", "disconnected"].includes(peer.connectionState) && state.realtimeVoiceActive) void finishRealtimeVoiceCall(`La conexión de voz se ha cerrado (${peer.connectionState}, ICE ${peer.iceConnectionState}).`);
  });
  const channel = peer.createDataChannel("oai-events");
  state.realtimeChannel = channel;
  channel.addEventListener("message", ({ data }) => { try { handleRealtimeEvent(JSON.parse(data)); } catch {} });
  channel.addEventListener("close", () => console.warn("[MyKOS Realtime] canal de eventos cerrado", { at: new Date().toISOString() }));
  channel.addEventListener("open", () => { if (state.realtimeVoiceActive) setVoiceButton("listening", "Micrófono abierto. Habla con normalidad."); });
  const offer = await peer.createOffer();
  await peer.setLocalDescription(offer);
  await waitForIceGathering(peer);
  const sdp = peer.localDescription?.sdp;
  if (!sdp) throw new Error("No se pudo crear la oferta de voz.");
  const result = await api("/api/sessions/" + encodeURIComponent(state.conversationId) + "/realtime", { method: "POST", body: JSON.stringify({ sdp }) });
  state.localVoiceCallId = result.call.callId;
  state.localVoiceCall = true;
  state.realtimeVoiceActive = true;
  setVoiceCallUi(true);
  setVoiceButton("connecting", "Conectando llamada Realtime…");
  await peer.setRemoteDescription({ type: "answer", sdp: result.transport.sdp });
}

// Gemini Live usa WebSocket directo con un token efímero de un solo uso. No se
// reutiliza el flujo WebRTC ni la credencial OAuth de OpenAI.
const GEMINI_LIVE_INPUT_RATE = 16_000;
const GEMINI_LIVE_OUTPUT_RATE = 24_000;

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x4000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunk, bytes.length)));
  }
  return btoa(binary);
}

function base64ToBytes(base64) {
  const binary = atob(String(base64 || ""));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function pcm16Base64(samples) {
  const pcm = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index] || 0));
    pcm[index] = sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff);
  }
  return bytesToBase64(new Uint8Array(pcm.buffer));
}

function stopGeminiLivePlayback() {
  for (const source of state.geminiLiveOutputSources) { try { source.stop(); } catch {} }
  state.geminiLiveOutputSources.clear();
  state.geminiLiveOutputAt = state.geminiLiveOutputContext?.currentTime || 0;
}

function playGeminiLivePcm(base64) {
  if (!state.geminiLiveActive || !base64) return;
  let bytes;
  try { bytes = base64ToBytes(base64); } catch { return; }
  const length = Math.floor(bytes.byteLength / 2);
  if (!length) return;
  const samples = new Float32Array(length);
  const view = new DataView(bytes.buffer, bytes.byteOffset, length * 2);
  for (let index = 0; index < length; index += 1) samples[index] = view.getInt16(index * 2, true) / 0x8000;

  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) return;
  const context = state.geminiLiveOutputContext || new Context({ sampleRate: GEMINI_LIVE_OUTPUT_RATE });
  state.geminiLiveOutputContext = context;
  void context.resume().catch(() => {});
  const buffer = context.createBuffer(1, samples.length, GEMINI_LIVE_OUTPUT_RATE);
  buffer.copyToChannel(samples, 0);
  const source = context.createBufferSource();
  source.buffer = buffer;
  if (!state.callRemoteAnalyser) {
    state.callRemoteAnalyser = context.createAnalyser();
    state.callRemoteAnalyser.fftSize = 1024;
    state.callRemoteAnalyser.connect(context.destination);
  }
  source.connect(state.callRemoteAnalyser);
  const startsAt = Math.max(context.currentTime + 0.04, state.geminiLiveOutputAt || 0);
  state.geminiLiveOutputAt = startsAt + buffer.duration;
  state.geminiLiveOutputSources.add(source);
  source.addEventListener("ended", () => state.geminiLiveOutputSources.delete(source), { once: true });
  source.start(startsAt);
}

async function startGeminiLiveCapture() {
  if (state.geminiLiveInputProcessor || !state.localVoiceStream || !state.geminiLiveActive) return;
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) throw new Error("Este navegador no puede procesar audio para Gemini Live.");
  const context = new Context({ sampleRate: GEMINI_LIVE_INPUT_RATE });
  state.geminiLiveInputContext = context;
  await context.resume().catch(() => {});
  const source = context.createMediaStreamSource(state.localVoiceStream);
  const processor = context.createScriptProcessor(2048, 1, 1);
  const sink = context.createGain();
  sink.gain.value = 0;
  processor.onaudioprocess = (event) => {
    const socket = state.geminiLiveSocket;
    if (!state.geminiLiveActive || socket?.readyState !== WebSocket.OPEN) return;
    const samples = event.inputBuffer.getChannelData(0);
    try {
      socket.send(JSON.stringify({
        realtimeInput: {
          audio: { mimeType: `audio/pcm;rate=${GEMINI_LIVE_INPUT_RATE}`, data: pcm16Base64(samples) },
        },
      }));
    } catch { /* el cierre del socket termina la llamada y libera el micrófono */ }
  };
  source.connect(processor);
  processor.connect(sink);
  sink.connect(context.destination);
  state.geminiLiveInputSource = source;
  state.geminiLiveInputProcessor = processor;
  state.geminiLiveInputSink = sink;
}

function geminiTranscriptId(role) {
  state.geminiLiveTranscriptCounter += 1;
  return `gemini_${role}_${state.geminiLiveTranscriptCounter}`;
}

async function parseGeminiLiveFrame(frame) {
  if (frame instanceof Blob) return JSON.parse(await frame.text());
  if (frame instanceof ArrayBuffer) return JSON.parse(new TextDecoder().decode(frame));
  return JSON.parse(String(frame));
}

async function handleGeminiLiveMessage(message) {
  if (message?.setupComplete) {
    await startGeminiLiveCapture();
    window.clearTimeout(state.geminiLiveSetupTimer);
    state.geminiLiveSetupTimer = 0;
    state.geminiLiveSetupResolve?.();
    state.geminiLiveSetupResolve = null;
    state.geminiLiveSetupReject = null;
    setVoiceButton("listening", "Micrófono abierto. Habla con normalidad.");
    return;
  }
  const providerError = String(message?.error?.message || message?.error?.status || message?.error || "").trim();
  if (providerError) {
    const error = new Error(providerError.slice(0, 500));
    state.geminiLiveSetupReject?.(error);
    state.geminiLiveSetupReject = null;
    if (state.geminiLiveActive) void finishGeminiLiveVoiceCall(error.message, { keepPanel: true });
    return;
  }
  const server = message?.serverContent || {};
  const toolCalls = Array.isArray(message?.toolCall?.functionCalls) ? message.toolCall.functionCalls : [];
  if (toolCalls.length) {
    const callId = String(state.localVoiceCallId || "").trim();
    if (!callId || !state.geminiLiveSocket || state.geminiLiveSocket.readyState !== WebSocket.OPEN) {
      throw new Error("MyKOS no tiene una llamada Gemini activa para ejecutar la herramienta.");
    }
    setVoiceButton("working", "Consultando una herramienta de MyKOS…");
    const forwarded = await api(`/api/calls/${encodeURIComponent(callId)}/gemini-tools`, {
      method: "POST",
      body: JSON.stringify({
        functionCalls: toolCalls,
        permission_mode: document.getElementById("permission-mode-select")?.value || "supervisado",
      }),
    });
    if (!forwarded?.ok || !Array.isArray(forwarded.functionResponses)) {
      throw new Error(String(forwarded?.message || forwarded?.error || "MyKOS no pudo ejecutar la herramienta solicitada."));
    }
    state.geminiLiveSocket.send(JSON.stringify({ toolResponse: { functionResponses: forwarded.functionResponses } }));
    return;
  }
  for (const part of server?.modelTurn?.parts || []) {
    if (part?.inlineData?.data) playGeminiLivePcm(part.inlineData.data);
  }
  const input = server?.inputTranscription;
  if (input?.finished && String(input.text || "").trim()) {
    const text = String(input.text).trim();
    callTranscriptLine("user", text);
    void saveRealtimeTranscript("user", text, geminiTranscriptId("user"));
  }
  const output = server?.outputTranscription;
  if (output?.finished && String(output.text || "").trim()) {
    const text = String(output.text).trim();
    callTranscriptLine("assistant", text);
    void saveRealtimeTranscript("assistant", text, geminiTranscriptId("assistant"));
  }
  if (server?.interrupted) {
    stopGeminiLivePlayback();
    if (state.geminiLiveActive) setVoiceButton("listening", "Te escucho.");
  } else if (server?.turnComplete && state.geminiLiveActive) {
    setVoiceButton("listening", "Micrófono abierto. Habla cuando quieras.");
  }
}

async function finishGeminiLiveVoiceCall(detail = "Llamada colgada", { keepPanel = false } = {}) {
  const socket = state.geminiLiveSocket;
  state.geminiLiveActive = false;
  state.geminiLiveClosing = true;
  window.clearTimeout(state.geminiLiveSetupTimer);
  state.geminiLiveSetupTimer = 0;
  state.geminiLiveSetupReject?.(new Error(detail));
  state.geminiLiveSetupResolve = null;
  state.geminiLiveSetupReject = null;
  state.geminiLiveSocket = null;
  if (socket) {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try { socket.close(1000, "MyKOS ended the call"); } catch {}
  }
  const callId = state.localVoiceCallId;
  state.localVoiceCall = false;
  await releaseVoiceMedia();
  if (callId) { try { await api("/api/calls/" + encodeURIComponent(callId), { method: "DELETE" }); } catch {} }
  state.localVoiceCallId = "";
  state.geminiLiveClosing = false;
  setVoiceCallUi(keepPanel);
  if (keepPanel && elements.voiceCallStage) {
    elements.voiceCallStatus.textContent = "No se ha podido conectar";
    elements.voiceCallDetail.textContent = detail;
  }
  setVoiceButton("idle", detail);
}

async function startGeminiLiveVoiceCall() {
  await ensureVoiceConversation();
  state.localVoiceCall = true;
  state.geminiLiveClosing = false;
  setVoiceCallUi(true);
  setVoiceButton("connecting", "Preparando Gemini Live…");
  const prepared = await api("/api/sessions/" + encodeURIComponent(state.conversationId) + "/gemini-live", { method: "POST", body: "{}" });
  const token = String(prepared?.transport?.token || "").trim();
  const endpoint = String(prepared?.transport?.endpoint || "").trim();
  if (prepared?.transport?.type !== "websocket" || !endpoint.startsWith("wss://") || !token.startsWith("auth_tokens/")) {
    throw new Error("MyKOS no ha recibido un token válido de Gemini Live.");
  }
  state.localVoiceCallId = String(prepared?.call?.callId || "");
  if (!state.localVoiceCallId) throw new Error("MyKOS no ha creado la llamada Gemini Live.");
  setVoiceButton("connecting", "Abriendo micrófono…");
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
  state.localVoiceStream = stream;
  try {
    state.callAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    await state.callAudioContext.resume().catch(() => {});
    state.callMicAnalyser = state.callAudioContext.createAnalyser();
    state.callMicAnalyser.fftSize = 1024;
    state.callAudioContext.createMediaStreamSource(stream).connect(state.callMicAnalyser);
  } catch { state.callMicAnalyser = null; }

  const socket = new WebSocket(`${endpoint}?access_token=${encodeURIComponent(token)}`);
  state.geminiLiveSocket = socket;
  state.geminiLiveActive = true;
  state.geminiLiveTranscriptCounter = 0;
  state.realtimeTranscriptIds.clear();
  setVoiceCallUi(true);
  setVoiceButton("connecting", "Conectando Gemini Live…");
  await new Promise((resolve, reject) => {
    state.geminiLiveSetupResolve = resolve;
    state.geminiLiveSetupReject = reject;
    state.geminiLiveSetupTimer = window.setTimeout(() => reject(new Error("Gemini Live no confirmó la conexión a tiempo.")), 15_000);
    socket.onopen = () => {
      try {
        socket.send(JSON.stringify({
          setup: {
            model: `models/${prepared.session.model}`,
            generationConfig: {
              responseModalities: ["AUDIO"],
              speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: prepared.session.voice } } },
            },
            systemInstruction: { parts: [{ text: "Habla en español de España de forma clara, natural y directa. Eres MyKOS, el asistente personal de MyKOS. Si te saluda por tu nombre, no vuelvas a presentarte, solo responde con naturalidad." }] },
            tools: [{ functionDeclarations: [
              { name: "get_local_status", description: "Consulta el estado básico de solo lectura de MyKOS y del equipo. No modifica nada.", parameters: { type: "OBJECT", properties: {} } },
              { name: "search_memory", description: "Busca recuerdos persistentes de MyKOS por palabras clave. Solo lectura.", parameters: { type: "OBJECT", properties: { query: { type: "STRING", description: "Palabras o frase que se quieren buscar." }, category: { type: "STRING", description: "Categoría opcional de memoria." }, max_results: { type: "INTEGER", description: "Máximo de resultados entre 1 y 6." } }, required: ["query"] } },
              { name: "list_automations", description: "Lista los recordatorios locales de MyKOS. Solo lectura.", parameters: { type: "OBJECT", properties: {} } },
              { name: "create_reminder", description: "Prepara un recordatorio local. MyKOS siempre pedirá aprobación explícita antes de crearlo.", parameters: { type: "OBJECT", properties: { title: { type: "STRING", description: "Título breve del recordatorio." }, message: { type: "STRING", description: "Texto opcional del recordatorio." }, run_at: { type: "STRING", description: "Fecha ISO futura con zona horaria." }, repeat_minutes: { type: "INTEGER", description: "0 para una vez o minutos de repetición." } }, required: ["title", "run_at"] } },
            ] }],
            inputAudioTranscription: {},
            outputAudioTranscription: {},
          },
        }));
      } catch (error) { reject(error); }
    };
    socket.onmessage = (event) => {
      void parseGeminiLiveFrame(event.data)
        .then(handleGeminiLiveMessage)
        .catch((error) => {
          state.geminiLiveSetupReject?.(error);
          if (state.geminiLiveActive) void finishGeminiLiveVoiceCall("Gemini Live devolvió una respuesta no válida.", { keepPanel: true });
        });
    };
    socket.onerror = () => {
      const error = new Error("No se ha podido conectar con Gemini Live.");
      state.geminiLiveSetupReject?.(error);
    };
    socket.onclose = (event) => {
      const reason = String(event.reason || "").trim();
      state.geminiLiveSetupReject?.(new Error(reason || "Gemini Live cerró la conexión."));
      if (state.geminiLiveActive && !state.geminiLiveClosing) {
        void finishGeminiLiveVoiceCall(reason ? `Gemini Live cerró la llamada: ${reason}` : "Gemini Live cerró la llamada.", { keepPanel: true });
      }
    };
  });
}

// Llamada local de reserva: «Llamar» abre el micrófono una vez. El VAD local
// delimita cada frase por silencio y «Colgar» cierra tanto audio como llamada Gateway.

async function ensureVoiceConversation() {
  if (state.conversationId) return state.conversationId;
  const data = await api("/api/conversations/new", { method: "POST", body: "{}" });
  state.conversationId = data.conversation.id;
  localStorage.setItem("mykos-conversation", state.conversationId);
  showWelcome();
  await loadConversations();
  return state.conversationId;
}

function voiceTurnId() {
  return window.crypto?.randomUUID?.() || ("voice-" + Date.now() + "-" + Math.random().toString(16).slice(2));
}

const VOICE_VAD = Object.freeze({ recordAfterMs: 80, startMs: 180, endMs: 900, minTurnMs: 250, maxTurnMs: 25_000 });

const CALL_MODE_TEXT = Object.freeze({
  listening: ["En llamada", "El micrófono sigue abierto."],
  hearing: ["Te escucho", "Responderé en cuanto guardes silencio."],
  speaking: ["MyKOS está hablando", "Puedes interrumpirle hablando."],
});

function formatCallTime(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${minutes}:${seconds}` : `${minutes}:${seconds}`;
}

// En la llamada Realtime el modo se deduce de los niveles reales de audio; el visual avisa aquí.
function onCallVisualMode(mode) {
  const stage = elements.voiceCallStage;
  if (!stage) return;
  stage.dataset.mode = mode;
  if ((!state.realtimeVoiceActive && !state.geminiLiveActive) || !CALL_MODE_TEXT[mode]) return;
  elements.voiceCallStatus.textContent = CALL_MODE_TEXT[mode][0];
  elements.voiceCallDetail.textContent = CALL_MODE_TEXT[mode][1];
}

function setCallTranscriptVisible(visible, { remember = true } = {}) {
  elements.voiceCallStage?.classList.toggle("transcript-hidden", !visible);
  elements.voiceTranscriptToggle?.setAttribute("aria-pressed", String(visible));
  if (remember) { try { localStorage.setItem("mykos-call-transcript", visible ? "on" : "off"); } catch { /* preferencia opcional */ } }
}

function callTranscriptLine(role, text) {
  state.callTranscript?.addLine(role, text);
}

function startCallVisual() {
  const firstStart = !state.callStartedAt;
  if (firstStart) state.callStartedAt = Date.now();
  if (!state.callTranscript && elements.voiceTranscriptList && window.MyKOSCallTranscript) {
    state.callTranscript = window.MyKOSCallTranscript.mount(elements.voiceTranscriptList, {
      emptyText: "La transcripción aparecerá aquí mientras hablas.",
    });
  }
  if (firstStart) {
    state.callTranscript?.reset();
    state.callEventTypes.clear();
  }
  if (!state.callTimerId && elements.voiceCallTimer) {
    const paint = () => { const t = formatCallTime(Date.now() - state.callStartedAt); elements.voiceCallTimer.textContent = t; if (elements.voiceCompactTimer) elements.voiceCompactTimer.textContent = t; };
    paint();
    state.callTimerId = setInterval(paint, 1000);
  }
  if (!state.callVisual && elements.voiceCallCanvas && window.MyKOSCallVisual) {
    state.callVisual = window.MyKOSCallVisual.mount(elements.voiceCallCanvas, {
      getMode: () => state.callVisualMode,
      getMicAnalyser: () => state.callMicAnalyser || state.localVoiceAnalyser,
      getVoiceAnalyser: () => state.callRemoteAnalyser,
      deriveMode: () => state.realtimeVoiceActive || state.geminiLiveActive,
      onMode: onCallVisualMode,
    });
  }
  state.callVisual?.start();
}

function stopCallVisual() {
  state.callTranscript?.finish();
  state.callVisual?.stop();
  state.callVisual = null;
  clearInterval(state.callTimerId);
  state.callTimerId = 0;
  state.callStartedAt = 0;
  if (elements.voiceCallTimer) elements.voiceCallTimer.textContent = "00:00"; if (elements.voiceCompactTimer) elements.voiceCompactTimer.textContent = "00:00";
}

function setVoiceCallUi(active) {
  elements.chatPanel.classList.toggle("voice-call-active", active);
  if (elements.voiceCallStage) elements.voiceCallStage.hidden = !active;
  if (active) {
    startCallVisual();
  } else {
    elements.chatPanel.classList.remove("voice-call-minimized");
    stopCallVisual();
  }
}
function updateVoiceCompactBar(mode) {
  if (elements.voiceCompactDot) elements.voiceCompactDot.dataset.mode = mode || "";
}

function setVoiceCallMinimized(minimized) {
  const panel = elements.chatPanel;
  if (minimized) {
    panel.classList.remove("voice-call-active");
    panel.classList.remove("models-active"); // cierra cualquier pagina abierta al minimizar
    panel.classList.add("voice-call-minimized");
    if (elements.voiceCallStage) elements.voiceCallStage.hidden = true;
    stopCallVisual();
  } else {
    panel.classList.remove("voice-call-minimized");
    panel.classList.add("voice-call-active");
    if (elements.voiceCallStage) elements.voiceCallStage.hidden = false;
    startCallVisual();
  }
}

function voiceLevel() {
  const analyser = state.localVoiceAnalyser;
  if (!analyser) return 0;
  const samples = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(samples);
  let total = 0;
  for (const sample of samples) {
    const value = (sample - 128) / 128;
    total += value * value;
  }
  return Math.sqrt(total / samples.length);
}

function voiceThreshold() {
  const sens = getVoiceSensitivity();
  if (sens === "high") {
    return Math.max(0.008, state.localVoiceNoiseFloor * 2.2 + 0.003);
  }
  if (sens === "low") {
    return Math.max(0.020, state.localVoiceNoiseFloor * 4.2 + 0.012);
  }
  return Math.max(0.012, state.localVoiceNoiseFloor * 3 + 0.006);
}

function stopActiveVoiceRecorder() {
  const recorder = state.localVoiceRecorder;
  if (recorder && recorder.state !== "inactive") recorder.stop();
}

async function interruptVoiceForBargeIn() {
  if (!state.localVoiceCall || state.localVoiceInterrupted) return;
  state.localVoiceInterrupted = true;
  state.localVoiceTurnAbort?.abort();
  if (state.localVoiceAudio) {
    state.localVoiceAudio.pause();
    state.localVoiceAudio.currentTime = 0;
  }
  state.localVoiceAudioResolver?.();
  const callId = state.localVoiceCallId;
  if (callId) {
    try { await api("/api/calls/" + encodeURIComponent(callId) + "/interrupt", { method: "POST", body: "{}" }); } catch { /* el turno puede haber acabado */ }
  }
}

function beginAutomaticVoiceRecording() {
  if (!state.localVoiceCall || state.localVoiceRecorder || !state.localVoiceStream || !window.MediaRecorder) return;
  const preferred = "audio/webm;codecs=opus";
  const options = MediaRecorder.isTypeSupported(preferred) ? { mimeType: preferred } : {};
  const chunks = [];
  const recorder = new MediaRecorder(state.localVoiceStream, options);
  state.localVoiceRecorder = recorder;
  state.localVoiceSegmentStartedAt = performance.now();
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data?.size) chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    if (state.localVoiceRecorder === recorder) state.localVoiceRecorder = null;
    const elapsed = performance.now() - state.localVoiceSegmentStartedAt;
    if (!state.localVoiceCall || !chunks.length || elapsed < VOICE_VAD.minTurnMs) return;
    const mimeType = recorder.mimeType || "audio/webm";
    queueAutomaticVoiceTurn(new Blob(chunks, { type: mimeType }), mimeType);
  }, { once: true });
  recorder.start();
  setVoiceButton("hearing", "Detectando tu voz. El turno se envía al guardar silencio.");
}

function monitorVoiceActivity() {
  if (!state.localVoiceCall || !state.localVoiceAnalyser) return;
  const now = performance.now();
  const level = voiceLevel();
  const isSpeaking = Boolean(state.localVoiceAudio);
  const isBusy = Boolean(state.busy);
  const baseThreshold = voiceThreshold();
  // Cuando MyKOS habla por los altavoces, elevamos el umbral para que el eco acústico
  // no se confunda con la voz del usuario ni dispare interrupciones accidentales.
  const threshold = isSpeaking ? Math.max(0.045, baseThreshold * 2.5) : baseThreshold;
  const speaking = level >= threshold;

  // Solo calibramos el ruido de fondo cuando la habitación está en silencio y MyKOS no habla.
  if (!speaking && !state.localVoiceRecorder && !isSpeaking && !isBusy) {
    state.localVoiceNoiseFloor = state.localVoiceNoiseFloor * 0.96 + level * 0.04;
  }

  if (speaking) {
    state.localVoiceSilenceSince = 0;
    state.localVoiceSpeechSince ||= now;
    const speechFor = now - state.localVoiceSpeechSince;
    const bargeInEnabled = getVoiceBargeInEnabled();
    if (isSpeaking || isBusy) {
      // Mientras MyKOS habla o procesa un turno, solo interrumpimos y grabamos si
      // barge-in está activo y la voz del usuario supera de forma sostenida el umbral de interrupción.
      const bargeInDelay = isSpeaking ? 480 : 380;
      if (bargeInEnabled && speechFor >= bargeInDelay) {
        void interruptVoiceForBargeIn();
        if (!state.localVoiceRecorder) {
          beginAutomaticVoiceRecording();
        }
      }
    } else {
      const recordDelay = VOICE_VAD.recordAfterMs;
      if (speechFor >= recordDelay && !state.localVoiceRecorder) {
        beginAutomaticVoiceRecording();
      }
    }
  } else {
    state.localVoiceSpeechSince = 0;
    if (state.localVoiceRecorder) {
      state.localVoiceSilenceSince ||= now;
      if (now - state.localVoiceSilenceSince >= getVoiceSilenceMs() || now - state.localVoiceSegmentStartedAt >= VOICE_VAD.maxTurnMs) {
        state.localVoiceSilenceSince = 0;
        stopActiveVoiceRecorder();
      }
    }
  }
  state.localVoiceFrame = requestAnimationFrame(monitorVoiceActivity);
}

async function openHandsFreeMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !window.AudioContext) {
    throw new Error("Este navegador no permite una llamada manos libres.");
  }
  state.localVoiceStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  state.localVoiceAudioContext = new AudioContext();
  await state.localVoiceAudioContext.resume();
  const source = state.localVoiceAudioContext.createMediaStreamSource(state.localVoiceStream);
  state.localVoiceAnalyser = state.localVoiceAudioContext.createAnalyser();
  state.localVoiceAnalyser.fftSize = 1024;
  source.connect(state.localVoiceAnalyser);
  state.callMicAnalyser = state.localVoiceAnalyser;
  state.callRemoteAnalyser = state.localVoiceAudioContext.createAnalyser();
  state.callRemoteAnalyser.fftSize = 1024;
  state.callRemoteAnalyser.connect(state.localVoiceAudioContext.destination);
  state.localVoiceNoiseFloor = 0.006;
  state.localVoiceSpeechSince = 0;
  state.localVoiceSilenceSince = 0;
  monitorVoiceActivity();
  setVoiceButton("listening", "Micrófono abierto. Habla con normalidad.");
}

function playVoiceAudioChunk(chunk) {
  if (!chunk?.audio || !state.localVoiceCall) return Promise.resolve(false);
  const audio = new Audio("data:" + (chunk.content_type || "audio/wav") + ";base64," + chunk.audio);
  return playPreparedAudio(audio);
}

function playPreparedAudio(audio) {
  if (!audio || !state.localVoiceCall) return Promise.resolve(false);
  try {
    audio.playbackRate = getVoicePlaybackRate();
  } catch {}
  try {
    if (state.localVoiceAudioContext?.state === "running" && state.callRemoteAnalyser) {
      const mediaSource = state.localVoiceAudioContext.createMediaElementSource(audio);
      mediaSource.connect(state.callRemoteAnalyser);
    }
  } catch {}
  state.localVoiceAudio = audio;
  return new Promise((resolve, reject) => {
    const finish = (ok) => {
      if (state.localVoiceAudio === audio) {
        state.localVoiceAudio = null;
        state.localVoiceAudioResolver = null;
      }
      resolve(ok);
    };
    state.localVoiceAudioResolver = () => finish(false);
    audio.addEventListener("ended", () => finish(true), { once: true });
    audio.addEventListener("error", () => reject(new Error("No se pudo reproducir la respuesta de voz.")), { once: true });
    audio.play().catch(reject);
  });
}

async function playVoiceAudio(chunks) {
  for (const chunk of chunks || []) {
    if (!state.localVoiceCall) return false;
    setVoiceButton("speaking", "MyKOS está hablando. Puedes interrumpirle hablando.");
    if (!(await playVoiceAudioChunk(chunk))) return false;
  }
  return true;
}

async function releaseVoiceMedia() {
  cancelAnimationFrame(state.localVoiceFrame);
  state.localVoiceFrame = 0;
  stopActiveVoiceRecorder();
  state.localVoiceRecorder = null;
  state.localVoiceChunks = [];
  state.localVoiceStream?.getTracks().forEach((track) => track.stop());
  state.localVoiceStream = null;
  state.localVoiceAnalyser = null;
  if (state.localVoiceAudioContext) await state.localVoiceAudioContext.close().catch(() => {});
  state.localVoiceAudioContext = null;
  state.callMicAnalyser = null;
  state.callRemoteAnalyser = null;
  if (state.callAudioContext) await state.callAudioContext.close().catch(() => {});
  state.callAudioContext = null;
  state.geminiLiveInputProcessor?.disconnect();
  state.geminiLiveInputSource?.disconnect();
  state.geminiLiveInputSink?.disconnect();
  state.geminiLiveInputProcessor = null;
  state.geminiLiveInputSource = null;
  state.geminiLiveInputSink = null;
  if (state.geminiLiveInputContext) await state.geminiLiveInputContext.close().catch(() => {});
  state.geminiLiveInputContext = null;
  for (const source of state.geminiLiveOutputSources) { try { source.stop(); } catch {} }
  state.geminiLiveOutputSources.clear();
  if (state.geminiLiveOutputContext) await state.geminiLiveOutputContext.close().catch(() => {});
  state.geminiLiveOutputContext = null;
  state.geminiLiveOutputAt = 0;
}

async function endLocalVoiceCall() {
  if (state.geminiLiveActive) {
    await finishGeminiLiveVoiceCall("Llamada colgada");
    return;
  }
  if (state.realtimeVoiceActive) {
    const channel = state.realtimeChannel;
    if (channel?.readyState === "open") {
      try { channel.send(JSON.stringify({ type: "session.close" })); } catch {}
    }
    await finishRealtimeVoiceCall("Llamada colgada");
    return;
  }
  const callId = state.localVoiceCallId;
  state.localVoiceCall = false;
  state.localVoiceStopping = true;
  state.localVoiceTurnAbort?.abort();
  await releaseVoiceMedia();
  if (state.localVoiceAudio) {
    state.localVoiceAudio.pause();
    state.localVoiceAudio.currentTime = 0;
  }
  state.localVoiceAudioResolver?.();
  state.localVoiceAudio = null;
  state.localVoiceAudioResolver = null;
  state.localVoiceTurnAbort = null;
  state.localVoiceInterrupted = false;
  if (callId) {
    try { await api("/api/calls/" + encodeURIComponent(callId) + "/interrupt", { method: "POST", body: "{}" }); } catch { /* cierre idempotente */ }
    try { await api("/api/calls/" + encodeURIComponent(callId), { method: "DELETE" }); } catch { /* cierre idempotente */ }
  }
  state.localVoiceCallId = "";
  state.localVoiceStopping = false;
  setVoiceCallUi(false);
  setVoiceButton("idle", "Llamada colgada");
}

function queueAutomaticVoiceTurn(blob, mimeType) {
  const job = async () => {
    if (!state.localVoiceCall || state.localVoiceStopping) return;
    await submitAutomaticVoiceTurn(blob, mimeType);
  };
  state.localVoiceQueue = state.localVoiceQueue.catch(() => {}).then(job);
}

async function submitAutomaticVoiceTurn(blob, mimeType) {
  const controller = new AbortController();
  state.localVoiceTurnAbort = controller;
  const extension = mimeType.includes("ogg") ? "ogg" : "webm";
  const form = new FormData();
  form.append("audio", blob, "voice." + extension);
  setVoiceButton("thinking", "Has terminado de hablar. Transcribiendo con Whisper local…");
  try {
    const transcriptionResponse = await fetch("/api/transcribe", { method: "POST", body: form, signal: controller.signal });
    const transcription = await transcriptionResponse.json().catch(() => ({}));
    if (!transcriptionResponse.ok) throw new Error(transcription.error || ("HTTP " + transcriptionResponse.status));
    const message = String(transcription.text || "").trim();
    if (!message) {
      if (state.localVoiceCall) setVoiceButton("listening", "No he entendido texto. Sigue hablando.");
      return;
    }
    callTranscriptLine("user", message);
    addBubble("user", message, false, [], new Date().toISOString());
    setVoiceButton("thinking", "MyKOS está pensando la respuesta…");
    await sendLocalVoiceMessage(message, controller.signal);
  } catch (error) {
    if (error?.name !== "AbortError" && state.localVoiceCall) setVoiceButton("listening", "Error de voz: " + (error.message || "desconocido"));
  } finally {
    if (state.localVoiceTurnAbort === controller) state.localVoiceTurnAbort = null;
  }
}

/** Turno de voz en NDJSON: avisa de cada frase al llegar y devuelve el resultado de la línea final "done". */
async function streamVoiceTurn(callId, body, signal, onPhrase) {
  const response = await fetch("/api/calls/" + encodeURIComponent(callId) + "/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const fail = (data) => {
    const failure = new Error(data?.error || ("HTTP " + response.status));
    failure.serverMessage = typeof data?.message === "string" ? data.message : "";
    return failure;
  };
  if (!response.ok || !response.body) {
    throw fail(await response.json().catch(() => ({ error: "Respuesta inválida del servidor." })));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let done = null;
  const handleLine = (raw) => {
    if (!raw.trim()) return;
    let line;
    try { line = JSON.parse(raw); } catch { return; }
    if (line.type === "phrase") onPhrase(line);
    else if (line.type === "done") done = line;
    else if (line.type === "error") throw fail(line);
  };
  for (;;) {
    const { value, done: finished } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: !finished });
    let index;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      handleLine(raw);
    }
    if (finished) break;
  }
  handleLine(buffer);
  if (!done) throw new Error("La respuesta de voz terminó sin resultado.");
  return done;
}

async function sendLocalVoiceMessage(message, signal) {
  const callId = state.localVoiceCallId;
  if (!callId) throw new Error("La llamada no está conectada.");
  state.busy = true;
  state.localVoiceInterrupted = false;
  const turnId = voiceTurnId();
  try {
    // Modo streaming: cada frase se reproduce en cuanto llega, en orden, sin esperar al resto.
    let playChain = Promise.resolve();
    let playbackStopped = false;
    let playbackError = null;
    let streamedPhrases = 0;
    let assistantBubbleRow = null;
    let accumulatedText = "";
    const enqueuePhrase = (piece) => {
      streamedPhrases += 1;
      const phraseText = String(piece?.phrase || "").trim();
      if (phraseText) {
        if (!assistantBubbleRow) {
          accumulatedText = phraseText;
          assistantBubbleRow = addBubble("assistant", accumulatedText, false, [], new Date().toISOString(), "", elements.model?.value || "");
        } else {
          accumulatedText += " " + phraseText;
          const textEl = assistantBubbleRow.querySelector(".message-text");
          if (textEl) {
            textEl.textContent = accumulatedText;
            elements.messages.scrollTop = elements.messages.scrollHeight;
          }
        }
        callTranscriptLine("assistant", phraseText);
      }
      let prepared = null;
      if (piece?.audio?.audio) {
        try {
          prepared = new Audio("data:" + (piece.audio.content_type || "audio/wav") + ";base64," + piece.audio.audio);
          prepared.preload = "auto";
        } catch {}
      }
      playChain = playChain.then(async () => {
        if (playbackStopped || playbackError || state.localVoiceInterrupted || !state.localVoiceCall) { playbackStopped = true; return; }
        setVoiceButton("speaking", "MyKOS está hablando. Puedes interrumpirle hablando.");
        try {
          const played = prepared ? await playPreparedAudio(prepared) : await playVoiceAudioChunk(piece.audio);
          if (!played) playbackStopped = true;
        } catch (error) { playbackError = error; }
      });
    };
    const data = await streamVoiceTurn(
      callId,
      {
        turnId,
        transcript: message,
        stream: true,
        permission_mode: document.getElementById("permission-mode-select")?.value || "supervisado",
      },
      signal,
      enqueuePhrase
    );
    const answer = String(data.text || "").trim();
    if (answer) {
      const cleanAnswer = unwrapJsonAnswer(answer);
      if (!assistantBubbleRow) {
        addBubble("assistant", cleanAnswer, false, [], new Date().toISOString(), "", elements.model?.value || "");
        callTranscriptLine("assistant", cleanAnswer);
      } else {
        const textEl = assistantBubbleRow.querySelector(".message-text");
        if (textEl) textEl.textContent = cleanAnswer;
      }
    }
    if (data.pending_action) await loadApprovals();
    await loadConversations(); await loadApprovals();
    if (streamedPhrases > 0) {
      // Esperar a que terminen de reproducirse las frases en cola
      await playChain;
    } else if (!data.pending_action && data.audio?.length) {
      await playVoiceAudio(data.audio);
    }
    await loadConversation();
    if (playbackError) throw playbackError;
  } finally {
    state.busy = false;
    if (state.localVoiceCall && !state.localVoiceAudio) setVoiceButton("listening", "Micrófono abierto. Habla cuando quieras.");
  }
}

async function getActiveVoiceMode() {
  try {
    const data = await api("/api/voice/mode");
    return data?.mode || "local";
  } catch {
    return "local";
  }
}

async function playInitialCallGreeting() {
  if (!state.localVoiceCall) return;
  const greetingText = "Hola, buenas, soy MyKOS, ¿en qué te puedo ayudar?";
  state.busy = true;
  state.localVoiceInterrupted = false;
  try {
    setVoiceButton("speaking", "Iniciando voz de MyKOS…");
    const ttsData = await api("/api/tts", {
      method: "POST",
      body: JSON.stringify({ text: greetingText }),
    });
    if (!state.localVoiceCall || state.localVoiceInterrupted) return;
    callTranscriptLine("assistant", greetingText);
    addBubble("assistant", greetingText, false, [], new Date().toISOString(), "", elements.model?.value || "");
    if (ttsData?.audio) {
      await playVoiceAudio([ttsData]);
    }
  } catch {
    // Si falla el saludo inicial, la llamada continúa igualmente con el micrófono abierto.
  } finally {
    state.busy = false;
    if (state.localVoiceCall && !state.localVoiceRecorder) {
      setVoiceButton("listening", "Micrófono abierto. Habla con normalidad.");
    }
  }
}

async function startVoiceTurn() {
  if (state.localVoiceCall || state.busy) return;
  const currentMode = await getActiveVoiceMode();
  if (currentMode === "gemini") {
    try {
      await startGeminiLiveVoiceCall();
      return;
    } catch (error) {
      const failure = error.serverMessage || error.message || "No se pudo iniciar la llamada Gemini Live.";
      await finishGeminiLiveVoiceCall(failure, { keepPanel: true });
      elements.voiceCallDetail.textContent = failure;
      return;
    }
  }
  if (currentMode === "cloud" && await realtimeEnabledInMyKOS()) {
    try {
      await startRealtimeVoiceCall();
      return;
    } catch (error) {
      const failure = error.serverMessage || error.message || "No se pudo iniciar la llamada Realtime.";
      await finishRealtimeVoiceCall(failure, { keepPanel: true });
      elements.voiceCallDetail.textContent = failure;
      return;
    }
  }
  try {
    await ensureVoiceConversation();
    state.localVoiceCall = true;
    setVoiceCallUi(true);
    setVoiceButton("connecting", "Abriendo micrófono…");
    const data = await api("/api/sessions/" + encodeURIComponent(state.conversationId) + "/calls", {
      method: "POST",
      body: JSON.stringify({ model: elements.model.value, replace: true }),
    });
    state.localVoiceCallId = data.callId;
    await openHandsFreeMicrophone();
    await playInitialCallGreeting();
  } catch (error) {
    const callId = state.localVoiceCallId;
    state.localVoiceCall = false;
    state.localVoiceCallId = "";
    if (callId) {
      try { await api("/api/calls/" + encodeURIComponent(callId) + "/interrupt", { method: "POST", body: "{}" }); } catch { /* cierre idempotente */ }
      try { await api("/api/calls/" + encodeURIComponent(callId), { method: "DELETE" }); } catch { /* cierre idempotente */ }
    }
    await releaseVoiceMedia();
    setVoiceCallUi(false);
    setVoiceButton("idle", error.message || "No se pudo iniciar la llamada.");
    elements.voiceCallDetail.textContent = error.message || "No se pudo iniciar la llamada."; addBubble("assistant", "Error al abrir la llamada: " + (error.message || "desconocido"), true);
  }
}

function toggleVoiceInput() {
  if (!state.localVoiceCall) {
    startVoiceTurn();
  } else {
    endLocalVoiceCall();
  }
}

elements.voiceHangupButton?.addEventListener("click", endLocalVoiceCall);
elements.voiceStageHangupButton?.addEventListener("click", endLocalVoiceCall);
elements.voiceMinimizeButton?.addEventListener("click", () => setVoiceCallMinimized(true));
elements.voiceCompactExpandButton?.addEventListener("click", () => setVoiceCallMinimized(false));
elements.voiceCompactHangupButton?.addEventListener("click", () => { setVoiceCallMinimized(false); endLocalVoiceCall(); });
elements.voiceTranscriptToggle?.addEventListener("click", () => setCallTranscriptVisible(elements.voiceCallStage.classList.contains("transcript-hidden")));
window.addEventListener("pagehide", () => {
  if (state.localVoiceCallId) {
    try {
      fetch("/api/calls/" + encodeURIComponent(state.localVoiceCallId), { method: "DELETE", keepalive: true }).catch(() => {});
    } catch {}
  }
});
{
  let savedTranscriptPreference = "on";
  try { savedTranscriptPreference = localStorage.getItem("mykos-call-transcript") || "on"; } catch { /* sin almacenamiento */ }
  setCallTranscriptVisible(savedTranscriptPreference !== "off", { remember: false });
}
let terminalCwd = "~";
const terminalHistory = [];
let terminalHistoryIndex = -1;

function shortenPath(p) {
  if (!p) return "~";
  return p;
}

function updateTerminalCwdBadge(newCwd) {
  terminalCwd = newCwd || terminalCwd;
  if (elements.terminalCwdBadge) {
    elements.terminalCwdBadge.textContent = `${shortenPath(terminalCwd)} $`;
    elements.terminalCwdBadge.title = terminalCwd;
  }
}

function appendTerminalBlock(command, output, exitCode, isRunning = false) {
  if (!elements.terminalScreen) return null;
  const block = document.createElement("div");
  block.className = "term-block";

  const line = document.createElement("div");
  line.className = "term-line";

  const promptSpan = document.createElement("span");
  promptSpan.className = "term-prompt";
  promptSpan.textContent = `mykos:${shortenPath(terminalCwd)}$ `;

  const cmdSpan = document.createElement("span");
  cmdSpan.className = "term-cmd";
  cmdSpan.textContent = command;

  line.appendChild(promptSpan);
  line.appendChild(cmdSpan);
  block.appendChild(line);

  if (isRunning) {
    const loading = document.createElement("div");
    loading.className = "term-loading";
    loading.textContent = "Ejecutando…";
    block.appendChild(loading);
  } else if (output) {
    const outPre = document.createElement("pre");
    outPre.className = `term-out ${exitCode !== 0 ? "term-err" : ""}`;
    outPre.textContent = output;
    block.appendChild(outPre);
  }

  elements.terminalScreen.appendChild(block);
  elements.terminalScreen.scrollTop = elements.terminalScreen.scrollHeight;
  return block;
}

async function runTerminalCommand(command) {
  const clean = String(command || "").trim();
  if (!clean) return;

  if (clean === "clear") {
    if (elements.terminalScreen) {
      elements.terminalScreen.innerHTML = "";
    }
    return;
  }

  terminalHistory.push(clean);
  terminalHistoryIndex = terminalHistory.length;

  const block = appendTerminalBlock(clean, "", 0, true);

  try {
    const res = await fetch("/terminal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: clean, cwd: terminalCwd })
    });
    const data = await res.json();
    if (block) {
      const loading = block.querySelector(".term-loading");
      if (loading) loading.remove();

      if (data.output) {
        const outPre = document.createElement("pre");
        outPre.className = `term-out ${data.exitCode !== 0 ? "term-err" : ""}`;
        outPre.textContent = data.output;
        block.appendChild(outPre);
      }
    }
    if (data.cwd) {
      updateTerminalCwdBadge(data.cwd);
    }
  } catch (err) {
    if (block) {
      const loading = block.querySelector(".term-loading");
      if (loading) loading.remove();
      const outPre = document.createElement("pre");
      outPre.className = "term-out term-err";
      outPre.textContent = "Error al ejecutar: " + (err.message || String(err));
      block.appendChild(outPre);
    }
  } finally {
    if (elements.terminalScreen) {
      elements.terminalScreen.scrollTop = elements.terminalScreen.scrollHeight;
    }
  }
}

function toggleRightSidebar() {
  if (elements.rightSidebar) {
    const isOpen = elements.rightSidebar.classList.toggle("open");
    document.querySelector(".app-shell")?.classList.toggle("right-sidebar-open", isOpen);
    if (isOpen) {
      setTimeout(() => elements.terminalInput?.focus(), 150);
    }
  }
}

function closeRightSidebar() {
  if (elements.rightSidebar) {
    elements.rightSidebar.classList.remove("open");
    document.querySelector(".app-shell")?.classList.remove("right-sidebar-open");
  }
}

elements.rightSidebarToggle?.addEventListener("click", toggleRightSidebar);
elements.rightSidebarClose?.addEventListener("click", closeRightSidebar);

elements.terminalForm?.addEventListener("submit", (e) => {
  e.preventDefault();
  const cmd = elements.terminalInput?.value || "";
  if (!cmd.trim()) return;
  elements.terminalInput.value = "";
  void runTerminalCommand(cmd);
});

elements.terminalInput?.addEventListener("keydown", (e) => {
  if (e.key === "ArrowUp") {
    e.preventDefault();
    if (terminalHistory.length === 0) return;
    if (terminalHistoryIndex > 0) {
      terminalHistoryIndex--;
      elements.terminalInput.value = terminalHistory[terminalHistoryIndex] || "";
    }
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    if (terminalHistoryIndex < terminalHistory.length - 1) {
      terminalHistoryIndex++;
      elements.terminalInput.value = terminalHistory[terminalHistoryIndex] || "";
    } else {
      terminalHistoryIndex = terminalHistory.length;
      elements.terminalInput.value = "";
    }
  }
});

document.querySelectorAll(".term-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const cmd = chip.dataset.cmd;
    if (cmd) {
      void runTerminalCommand(cmd);
      elements.terminalInput?.focus();
    }
  });
});

elements.terminalClearBtn?.addEventListener("click", () => {
  if (elements.terminalScreen) {
    elements.terminalScreen.innerHTML = "";
  }
  elements.terminalInput?.focus();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (elements.rightSidebar?.classList.contains("open")) closeRightSidebar();
    if (!document.querySelector(".app-shell")?.classList.contains("sidebar-collapsed")) {
      document.querySelector(".app-shell")?.classList.add("sidebar-collapsed");
      localStorage.setItem("mykos-sidebar-hidden", "true");
      document.querySelectorAll(".sidebar-toggle").forEach((btn) => {
        btn.setAttribute("aria-expanded", "false");
        btn.title = "Mostrar panel lateral";
        btn.setAttribute("aria-label", "Mostrar panel lateral");
      });
    }
  }
});

elements.fileInput.addEventListener("change", () => uploadFiles(elements.fileInput.files));
elements.voiceInputButton.addEventListener("click", toggleVoiceInput);
elements.dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.dropzone.classList.add("dragging");
});
elements.dropzone.addEventListener("dragleave", () => elements.dropzone.classList.remove("dragging"));
elements.dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.dropzone.classList.remove("dragging");
  uploadFiles(event.dataTransfer.files);
});

showWelcome();
initConversationToggle();
loadBenchmarkResults();
loadModels();
loadConversations();
loadConversation();
loadApprovals();
loadPermissions();
loadVoiceMode();
loadOllamaJobs();
loadAutomations();
state.automationPollTimer = window.setInterval(loadAutomations, 5000);
loadManagement();
renderLibraryRoots();
loadSwarmStatus({ schedule: true });

const urlParams = new URLSearchParams(window.location.search);
const initPage = urlParams.get("page");
if (initPage) {
  setTimeout(() => {
    setPage(initPage);
    const initTab = urlParams.get("tab");
    if (initTab && typeof setSettingsTab === "function") setSettingsTab(initTab);
  }, 350);
}

// ───────────────────────── Cortex (Grafo & Cerebro) ─────────────────────────
const cortexState = {
  initialized: false,
  loading: false,
  nodes: [],
  nodeMap: new Map(),
  edges: [],
  adjMap: new Map(),
  stats: { notes: 0, ghosts: 0, edges: 0 },
  camera: { x: 0, y: 0, zoom: 1 },
  viewport: { width: 800, height: 600, dpr: 1 },
  alpha: 0,
  rafId: 0,
  dragNode: null,
  panning: false,
  panOrigin: null,
  pointerDown: null,
  didMove: false,
  hoverNode: null,
  selectedId: null,
  activePath: null,
  editMode: false,
  searchQuery: "",
  matchedIds: new Set(),
  searchTimer: null,
  resizeObserver: null,
};

function setCortexStatus(message = "", isError = false) {
  if (!elements.cortexNoteStatus) return;
  if (!message) {
    elements.cortexNoteStatus.hidden = true;
    elements.cortexNoteStatus.textContent = "";
    elements.cortexNoteStatus.classList.remove("is-error");
    return;
  }
  elements.cortexNoteStatus.hidden = false;
  elements.cortexNoteStatus.textContent = message;
  elements.cortexNoteStatus.classList.toggle("is-error", Boolean(isError));
}

function setCortexEditMode(editing) {
  cortexState.editMode = Boolean(editing);
  if (elements.cortexNoteViewer) {
    elements.cortexNoteViewer.hidden = cortexState.editMode;
    elements.cortexNoteViewer.style.display = cortexState.editMode ? "none" : "block";
  }
  if (elements.cortexNoteEditor) {
    elements.cortexNoteEditor.hidden = !cortexState.editMode;
    elements.cortexNoteEditor.style.display = cortexState.editMode ? "block" : "none";
  }
  if (elements.cortexNoteSave) {
    elements.cortexNoteSave.hidden = !cortexState.editMode;
    elements.cortexNoteSave.style.display = cortexState.editMode ? "inline-block" : "none";
    elements.cortexNoteSave.disabled = !cortexState.editMode;
  }
  if (elements.cortexModeToggle) {
    elements.cortexModeToggle.textContent = cortexState.editMode ? "Cancelar" : "Editar";
    elements.cortexModeToggle.classList.toggle("danger-text-button", cortexState.editMode);
  }
  if (cortexState.editMode && elements.cortexNoteEditor) {
    elements.cortexNoteEditor.focus();
  }
}

function appendInlineMarkdown(parent, text) {
  const tokenRe = /(\[\[[^\]]+\]\]|`[^`\n]+`|\*\*[^*\n]+\*\*)/g;
  let lastIndex = 0;
  let match;
  while ((match = tokenRe.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parent.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    }
    const token = match[0];
    if (token.startsWith("[[") && token.endsWith("]]")) {
      const inner = token.slice(2, -2);
      const bar = inner.indexOf("|");
      const targetName = (bar > 0 ? inner.slice(0, bar) : inner).split("#")[0].trim();
      const display = (bar > 0 ? inner.slice(bar + 1) : inner).trim();
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cortex-wikilink";
      btn.textContent = display || targetName;
      btn.addEventListener("click", () => navigateCortexByName(targetName));
      parent.appendChild(btn);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.appendChild(code);
    } else if (token.startsWith("**") && token.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.appendChild(strong);
    }
    lastIndex = tokenRe.lastIndex;
  }
  if (lastIndex < text.length) {
    parent.appendChild(document.createTextNode(text.slice(lastIndex)));
  }
}

function renderCortexMarkdown(container, markdown) {
  if (!container) return;
  container.replaceChildren();
  let body = String(markdown || "");
  if (body.startsWith("---\n") || body.startsWith("---\r\n")) {
    const endIdx = body.indexOf("\n---", 3);
    if (endIdx !== -1) {
      const after = body.indexOf("\n", endIdx + 4);
      body = after !== -1 ? body.slice(after + 1) : "";
    }
  }
  const lines = body.replace(/\r\n/g, "\n").split("\n");
  let inCode = false;
  let codeLines = [];
  let listEl = null;

  const flushList = () => {
    if (listEl) {
      container.appendChild(listEl);
      listEl = null;
    }
  };

  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      flushList();
      if (!inCode) {
        inCode = true;
        codeLines = [];
      } else {
        inCode = false;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        container.appendChild(pre);
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    const headingMatch = line.match(/^(#{1,4})\s+(.*)$/);
    if (headingMatch) {
      flushList();
      const level = headingMatch[1].length;
      const h = document.createElement(`h${level}`);
      appendInlineMarkdown(h, headingMatch[2]);
      container.appendChild(h);
      continue;
    }
    const listMatch = line.match(/^\s*[-*]\s+(.*)$/);
    if (listMatch) {
      if (!listEl) listEl = document.createElement("ul");
      const li = document.createElement("li");
      appendInlineMarkdown(li, listMatch[1]);
      listEl.appendChild(li);
      continue;
    }
    flushList();
    if (!line.trim()) continue;
    const p = document.createElement("p");
    appendInlineMarkdown(p, line);
    container.appendChild(p);
  }
  flushList();
  if (!container.childNodes.length) {
    const empty = document.createElement("p");
    empty.className = "cortex-empty-hint";
    empty.textContent = "Nota vacía. Pulsa «Editar» para añadir contenido.";
    container.appendChild(empty);
  }
}

function navigateCortexByName(name) {
  const clean = String(name || "").trim();
  if (!clean) return;
  const low = clean.toLowerCase();
  const match = cortexState.nodes.find((node) => (
    node.label.toLowerCase() === low ||
    (node.path && node.path.toLowerCase() === low) ||
    (node.path && node.path.toLowerCase() === `${low}.md`)
  ));
  if (match) {
    selectCortexNode(match);
  } else {
    openGhostDraft(clean);
  }
}

function openGhostDraft(label) {
  const safeName = String(label || "Nueva Nota").replace(/[\\:*?"<>|]/g, "").trim() || "Nueva Nota";
  const draftPath = safeName.toLowerCase().endsWith(".md") ? safeName : `${safeName}.md`;
  cortexState.activePath = draftPath;
  cortexState.originalContent = `# ${safeName}\n\n`;
  if (elements.cortexNoteTitle) elements.cortexNoteTitle.textContent = safeName;
  if (elements.cortexNotePath) elements.cortexNotePath.textContent = `${draftPath} (nueva nota desde fantasma)`;
  if (elements.cortexNoteTags) {
    elements.cortexNoteTags.replaceChildren();
    elements.cortexNoteTags.hidden = true;
  }
  if (elements.cortexNoteEditor) {
    elements.cortexNoteEditor.value = cortexState.originalContent;
  }
  if (elements.cortexModeToggle) elements.cortexModeToggle.disabled = false;
  if (elements.cortexNoteSave) elements.cortexNoteSave.disabled = false;
  if (elements.cortexBacklinksCount) elements.cortexBacklinksCount.textContent = "0";
  if (elements.cortexBacklinksList) elements.cortexBacklinksList.replaceChildren();
  renderCortexMarkdown(elements.cortexNoteViewer, cortexState.originalContent);
  setCortexEditMode(true);
  setCortexStatus("Nodo fantasma listo: edita y pulsa Guardar para crear la nota.");
}

async function loadCortexNote(relativePath) {
  if (!relativePath) return;
  setCortexStatus("Cargando nota...");
  try {
    const note = await api(`/api/cortex/note?path=${encodeURIComponent(relativePath)}`);
    cortexState.activePath = note.path;
    cortexState.originalContent = note.content || "";
    if (elements.cortexNoteTitle) elements.cortexNoteTitle.textContent = note.title || note.path;
    if (elements.cortexNotePath) elements.cortexNotePath.textContent = note.path;
    if (elements.cortexNoteEditor) elements.cortexNoteEditor.value = note.content || "";
    if (elements.cortexModeToggle) elements.cortexModeToggle.disabled = false;
    if (elements.cortexNoteSave) elements.cortexNoteSave.disabled = true;

    if (elements.cortexNoteTags) {
      elements.cortexNoteTags.replaceChildren();
      const tags = Array.isArray(note.tags) ? note.tags : [];
      for (const tag of tags) {
        const pill = document.createElement("span");
        pill.className = "cortex-tag-pill";
        pill.textContent = tag;
        elements.cortexNoteTags.appendChild(pill);
      }
      elements.cortexNoteTags.hidden = tags.length === 0;
    }

    renderCortexMarkdown(elements.cortexNoteViewer, note.content || "");
    setCortexEditMode(false);

    const backlinks = Array.isArray(note.backlinks) ? note.backlinks : [];
    if (elements.cortexBacklinksCount) elements.cortexBacklinksCount.textContent = String(backlinks.length);
    if (elements.cortexBacklinksList) {
      elements.cortexBacklinksList.replaceChildren();
      if (backlinks.length === 0) {
        const empty = document.createElement("span");
        empty.className = "cortex-empty-hint";
        empty.textContent = "Sin enlaces entrantes.";
        elements.cortexBacklinksList.appendChild(empty);
      } else {
        for (const bl of backlinks) {
          const chip = document.createElement("button");
          chip.type = "button";
          chip.className = "cortex-backlink-chip";
          chip.textContent = bl.source.replace(/\.md$/i, "");
          chip.title = bl.source;
          chip.addEventListener("click", () => {
            const targetNode = cortexState.nodeMap.get(bl.id) || cortexState.nodes.find((n) => n.path === bl.source);
            if (targetNode) selectCortexNode(targetNode);
            else loadCortexNote(bl.source);
          });
          elements.cortexBacklinksList.appendChild(chip);
        }
      }
    }
    setCortexStatus("");
  } catch (error) {
    setCortexStatus(error.message || "No se pudo cargar la nota.", true);
  }
}

async function saveCortexNote() {
  if (!cortexState.activePath || !elements.cortexNoteEditor) return;
  const pathToSave = cortexState.activePath;
  const content = elements.cortexNoteEditor.value;
  if (elements.cortexNoteSave) elements.cortexNoteSave.disabled = true;
  setCortexStatus("Guardando nota y actualizando grafo...");
  try {
    await api("/api/cortex/note", {
      method: "POST",
      body: JSON.stringify({ path: pathToSave, content }),
    });
    renderCortexMarkdown(elements.cortexNoteViewer, content);
    await loadCortexGraph({ fitOnFirst: false });
    await loadCortexNote(pathToSave);
    const updatedNode = cortexState.nodes.find((n) => n.path === pathToSave);
    if (updatedNode) cortexState.selectedId = updatedNode.id;
    setCortexStatus("Nota guardada y grafo actualizado.");
  } catch (error) {
    setCortexStatus(error.message || "Error al guardar la nota.", true);
    if (elements.cortexNoteSave) elements.cortexNoteSave.disabled = false;
  }
}

function selectCortexNode(node) {
  if (!node) return;
  cortexState.selectedId = node.id;
  ensureCortexLoop();
  if (node.type === "unresolved" || !node.path) {
    openGhostDraft(node.label);
  } else {
    loadCortexNote(node.path);
  }
}

function applyCortexGraphData(data, { fitOnFirst = false } = {}) {
  const prevPositions = new Map(cortexState.nodes.map((n) => [n.id, { x: n.x, y: n.y, vx: n.vx, vy: n.vy }]));
  const rawNodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const rawEdges = Array.isArray(data?.edges) ? data.edges : [];
  const hadNodes = prevPositions.size > 0;

  const nodes = rawNodes.map((n, index) => {
    const prev = prevPositions.get(n.id);
    const angle = (index / Math.max(1, rawNodes.length)) * Math.PI * 2;
    const radius = 140 + (index % 5) * 35;
    return {
      ...n,
      r: Math.max(5.5, Math.min(15, 5 + Math.sqrt((n.weight || 0) + 1) * 1.65)),
      x: prev ? prev.x : Math.cos(angle) * radius + (Math.random() - 0.5) * 24,
      y: prev ? prev.y : Math.sin(angle) * radius + (Math.random() - 0.5) * 24,
      vx: prev ? prev.vx : 0,
      vy: prev ? prev.vy : 0,
    };
  });

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const edges = rawEdges
    .map((e) => ({ ...e, src: nodeMap.get(e.source), dst: nodeMap.get(e.target) }))
    .filter((e) => e.src && e.dst);

  const adjMap = new Map();
  for (const e of edges) {
    if (!adjMap.has(e.source)) adjMap.set(e.source, new Set());
    if (!adjMap.has(e.target)) adjMap.set(e.target, new Set());
    adjMap.get(e.source).add(e.target);
    adjMap.get(e.target).add(e.source);
  }

  cortexState.nodes = nodes;
  cortexState.nodeMap = nodeMap;
  cortexState.edges = edges;
  cortexState.adjMap = adjMap;
  cortexState.stats = data?.stats || {
    notes: nodes.filter((n) => n.type === "note").length,
    ghosts: nodes.filter((n) => n.type === "unresolved").length,
    edges: edges.length,
  };

  if (elements.cortexStats) {
    const s = cortexState.stats;
    elements.cortexStats.textContent = `${s.notes ?? 0} notas · ${s.edges ?? 0} enlaces · ${s.ghosts ?? 0} fantasmas`;
  }

  if (cortexState.searchQuery) updateLocalSearchMatches();
  cortexState.alpha = hadNodes ? 0.45 : 1.0;
  if (!hadNodes || fitOnFirst) fitCortexGraph();
  ensureCortexLoop();
}

async function loadCortexGraph({ fitOnFirst = false } = {}) {
  if (cortexState.loading) return;
  cortexState.loading = true;
  if (elements.cortexRefresh) elements.cortexRefresh.disabled = true;
  try {
    const data = await api("/api/cortex/graph");
    applyCortexGraphData(data, { fitOnFirst });
  } catch (error) {
    setCortexStatus(error.message || "No se pudo cargar el grafo de Cortex.", true);
  } finally {
    cortexState.loading = false;
    if (elements.cortexRefresh) elements.cortexRefresh.disabled = false;
  }
}

function fitCortexGraph() {
  const { width, height } = cortexState.viewport;
  if (!cortexState.nodes.length || !width || !height) {
    cortexState.camera = { x: 0, y: 0, zoom: 1 };
    return;
  }
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const n of cortexState.nodes) {
    if (n.x < minX) minX = n.x;
    if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.y > maxY) maxY = n.y;
  }
  const spanX = Math.max(120, maxX - minX + 120);
  const spanY = Math.max(120, maxY - minY + 120);
  const zoom = Math.max(0.25, Math.min(2.0, Math.min(width / spanX, height / spanY) * 0.85));
  cortexState.camera.x = (minX + maxX) / 2;
  cortexState.camera.y = (minY + maxY) / 2;
  cortexState.camera.zoom = zoom;
  drawCortexGraph();
}

function resizeCortexCanvas() {
  const canvas = elements.cortexCanvas;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  cortexState.viewport = { width: rect.width, height: rect.height, dpr };
  const targetW = Math.round(rect.width * dpr);
  const targetH = Math.round(rect.height * dpr);
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW;
    canvas.height = targetH;
  }
  drawCortexGraph();
}

function screenToWorld(sx, sy) {
  const { width, height } = cortexState.viewport;
  const { x, y, zoom } = cortexState.camera;
  return {
    x: (sx - width / 2) / zoom + x,
    y: (sy - height / 2) / zoom + y,
  };
}

function findNodeAtScreen(sx, sy) {
  const w = screenToWorld(sx, sy);
  const hitPad = 6 / Math.max(0.4, cortexState.camera.zoom);
  for (let i = cortexState.nodes.length - 1; i >= 0; i -= 1) {
    const n = cortexState.nodes[i];
    const dx = w.x - n.x;
    const dy = w.y - n.y;
    const r = n.r + hitPad;
    if (dx * dx + dy * dy <= r * r) return n;
  }
  return null;
}

function stepCortexPhysics() {
  const nodes = cortexState.nodes;
  const edges = cortexState.edges;
  const alpha = cortexState.alpha;
  if (!nodes.length || (alpha <= 0.002 && !cortexState.dragNode)) return false;

  const nCount = nodes.length;
  // Repulsión entre pares + gravedad suave al origen
  for (let i = 0; i < nCount; i += 1) {
    const a = nodes[i];
    a.vx += -a.x * 0.015 * alpha;
    a.vy += -a.y * 0.015 * alpha;
    for (let j = i + 1; j < nCount; j += 1) {
      const b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let distSq = dx * dx + dy * dy;
      if (distSq < 1) {
        dx = (Math.random() - 0.5) * 2;
        dy = (Math.random() - 0.5) * 2;
        distSq = dx * dx + dy * dy + 1;
      }
      const clampedSq = Math.max(324, distSq);
      const force = (2600 / clampedSq) * alpha;
      const dist = Math.sqrt(distSq);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx -= fx;
      a.vy -= fy;
      b.vx += fx;
      b.vy += fy;
    }
  }

  // Muelles en aristas
  const targetLen = 125;
  for (const e of edges) {
    const a = e.src;
    const b = e.dst;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const displacement = (dist - targetLen) * 0.055 * alpha;
    const fx = (dx / dist) * displacement;
    const fy = (dy / dist) * displacement;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }

  // Integración y amortiguación
  for (const n of nodes) {
    if (n === cortexState.dragNode) {
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx *= 0.8;
    n.vy *= 0.8;
    n.x += n.vx;
    n.y += n.vy;
  }

  if (!cortexState.dragNode) {
    cortexState.alpha *= 0.982;
  }
  return true;
}

function drawCortexGraph() {
  const canvas = elements.cortexCanvas;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const { width, height, dpr } = cortexState.viewport;
  const { x: camX, y: camY, zoom } = cortexState.camera;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  ctx.save();
  ctx.translate(width / 2, height / 2);
  ctx.scale(zoom, zoom);
  ctx.translate(-camX, -camY);

  const focusId = cortexState.hoverNode?.id || cortexState.selectedId;
  const focusNeighbors = focusId ? cortexState.adjMap.get(focusId) : null;
  const hasSearch = cortexState.searchQuery.length > 0;

  // Aristas
  for (const e of cortexState.edges) {
    const connected = focusId && (e.source === focusId || e.target === focusId);
    const searchDim = hasSearch && !cortexState.matchedIds.has(e.source) && !cortexState.matchedIds.has(e.target);
    ctx.beginPath();
    ctx.moveTo(e.src.x, e.src.y);
    ctx.lineTo(e.dst.x, e.dst.y);
    if (connected) {
      ctx.strokeStyle = "rgba(6, 182, 212, 0.78)";
      ctx.lineWidth = 1.8 / zoom;
    } else if (searchDim || (focusId && !connected)) {
      ctx.strokeStyle = "rgba(6, 182, 212, 0.08)";
      ctx.lineWidth = 1 / zoom;
    } else {
      ctx.strokeStyle = "rgba(6, 182, 212, 0.25)";
      ctx.lineWidth = 1.15 / zoom;
    }
    ctx.stroke();
  }

  // Nodos
  for (const n of cortexState.nodes) {
    const isGhost = n.type === "unresolved";
    const isSelected = n.id === cortexState.selectedId;
    const isHovered = n.id === cortexState.hoverNode?.id;
    const isNeighbor = Boolean(focusNeighbors && focusNeighbors.has(n.id));
    const isMatched = hasSearch && cortexState.matchedIds.has(n.id);

    let alpha = 1;
    if (hasSearch && !isMatched && !isSelected && !isHovered) {
      alpha = 0.18;
    } else if (focusId && !isSelected && !isHovered && !isNeighbor) {
      alpha = 0.35;
    }

    ctx.save();
    ctx.globalAlpha = alpha;

    if (isMatched || isSelected || isHovered) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 4.5, 0, Math.PI * 2);
      ctx.fillStyle = isMatched ? "rgba(250, 204, 21, 0.28)" : "rgba(6, 182, 212, 0.25)";
      ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    ctx.fillStyle = isGhost ? "#06b6d4" : (isHovered || isSelected ? "#f87171" : "#ef4444");
    ctx.fill();
    ctx.lineWidth = (isSelected || isHovered || isMatched ? 2.2 : 1.2) / Math.max(0.7, zoom);
    ctx.strokeStyle = isMatched ? "#facc15" : (isGhost ? "#0891b2" : "#dc2626");
    ctx.stroke();

    // Etiquetas legibles según zoom o foco
    if (zoom >= 0.62 || isHovered || isSelected || isMatched) {
      const fontSize = Math.max(9.5, Math.min(13, 11.5 / Math.sqrt(Math.max(0.45, zoom))));
      ctx.font = `${isSelected || isHovered || isMatched ? "600 " : ""}${fontSize}px system-ui, -apple-system, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = isMatched ? "#fef08a" : "rgba(226, 232, 240, 0.92)";
      ctx.fillText(n.label, n.x, n.y + n.r + 4);
    }

    ctx.restore();
  }

  ctx.restore();
}

function runCortexFrame() {
  cortexState.rafId = 0;
  if (!elements.cortexPage || elements.cortexPage.hidden) return;
  const active = stepCortexPhysics();
  drawCortexGraph();
  if (active) {
    cortexState.rafId = window.requestAnimationFrame(runCortexFrame);
  }
}

function ensureCortexLoop() {
  if (cortexState.rafId || !elements.cortexPage || elements.cortexPage.hidden) return;
  cortexState.rafId = window.requestAnimationFrame(runCortexFrame);
}

function stopCortexLoop() {
  if (cortexState.rafId) {
    window.cancelAnimationFrame(cortexState.rafId);
    cortexState.rafId = 0;
  }
}

function updateCortexTooltip(node, sx, sy) {
  const tip = elements.cortexTooltip;
  if (!tip) return;
  if (!node) {
    tip.hidden = true;
    return;
  }
  tip.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = node.label;
  const typeSpan = document.createElement("span");
  typeSpan.className = "cortex-tooltip-type";
  typeSpan.textContent = node.type === "unresolved" ? "Fantasma (sin crear)" : "Nota";
  tip.appendChild(title);
  tip.appendChild(typeSpan);
  tip.style.left = `${Math.min(cortexState.viewport.width - 190, Math.max(8, sx + 14))}px`;
  tip.style.top = `${Math.min(cortexState.viewport.height - 54, Math.max(8, sy + 14))}px`;
  tip.hidden = false;
}

function updateLocalSearchMatches() {
  const q = cortexState.searchQuery.toLowerCase();
  const matched = new Set();
  if (q) {
    for (const n of cortexState.nodes) {
      const inLabel = n.label.toLowerCase().includes(q);
      const inPath = n.path && n.path.toLowerCase().includes(q);
      const inTags = Array.isArray(n.tags) && n.tags.some((t) => t.toLowerCase().includes(q));
      const inAliases = Array.isArray(n.aliases) && n.aliases.some((a) => a.toLowerCase().includes(q));
      if (inLabel || inPath || inTags || inAliases) matched.add(n.id);
    }
  }
  cortexState.matchedIds = matched;
}

async function runCortexSearch(query) {
  cortexState.searchQuery = String(query || "").trim();
  updateLocalSearchMatches();
  drawCortexGraph();

  if (cortexState.searchTimer) window.clearTimeout(cortexState.searchTimer);
  if (!cortexState.searchQuery) return;

  const snapshotQuery = cortexState.searchQuery;
  cortexState.searchTimer = window.setTimeout(async () => {
    try {
      const data = await api(`/api/cortex/search?q=${encodeURIComponent(snapshotQuery)}`);
      if (cortexState.searchQuery !== snapshotQuery) return;
      for (const item of data?.results || []) {
        if (item.id) cortexState.matchedIds.add(item.id);
      }
      drawCortexGraph();
    } catch {
      // Mantiene las coincidencias locales si falla la consulta remota
    }
  }, 160);
}

function initCortexCanvasEvents() {
  if (cortexState.initialized) return;
  cortexState.initialized = true;

  const canvas = elements.cortexCanvas;
  if (canvas) {
    if (typeof ResizeObserver === "function") {
      cortexState.resizeObserver = new ResizeObserver(() => resizeCortexCanvas());
      cortexState.resizeObserver.observe(canvas.parentElement || canvas);
    }
    window.addEventListener("resize", () => {
      if (elements.cortexPage && !elements.cortexPage.hidden) resizeCortexCanvas();
    });

    canvas.addEventListener("pointerdown", (event) => {
      const rect = canvas.getBoundingClientRect();
      const sx = event.clientX - rect.left;
      const sy = event.clientY - rect.top;
      canvas.setPointerCapture(event.pointerId);
      cortexState.pointerDown = { x: sx, y: sy };
      cortexState.didMove = false;
      const hit = findNodeAtScreen(sx, sy);
      if (hit) {
        cortexState.dragNode = hit;
        cortexState.alpha = Math.max(cortexState.alpha, 0.35);
        canvas.classList.add("is-dragging");
        ensureCortexLoop();
      } else {
        cortexState.panning = true;
        cortexState.panOrigin = { x: sx, y: sy, camX: cortexState.camera.x, camY: cortexState.camera.y };
        canvas.classList.add("is-dragging");
      }
    });

    canvas.addEventListener("pointermove", (event) => {
      const rect = canvas.getBoundingClientRect();
      const sx = event.clientX - rect.left;
      const sy = event.clientY - rect.top;

      if (cortexState.pointerDown) {
        const dx = sx - cortexState.pointerDown.x;
        const dy = sy - cortexState.pointerDown.y;
        if (dx * dx + dy * dy > 16) cortexState.didMove = true;
      }

      if (cortexState.dragNode) {
        const w = screenToWorld(sx, sy);
        cortexState.dragNode.x = w.x;
        cortexState.dragNode.y = w.y;
        cortexState.alpha = Math.max(cortexState.alpha, 0.25);
        updateCortexTooltip(cortexState.dragNode, sx, sy);
        ensureCortexLoop();
        return;
      }

      if (cortexState.panning && cortexState.panOrigin) {
        const zoom = cortexState.camera.zoom;
        cortexState.camera.x = cortexState.panOrigin.camX - (sx - cortexState.panOrigin.x) / zoom;
        cortexState.camera.y = cortexState.panOrigin.camY - (sy - cortexState.panOrigin.y) / zoom;
        drawCortexGraph();
        return;
      }

      const hit = findNodeAtScreen(sx, sy);
      if (hit !== cortexState.hoverNode) {
        cortexState.hoverNode = hit;
        canvas.classList.toggle("is-hovering", Boolean(hit));
        drawCortexGraph();
      }
      updateCortexTooltip(hit, sx, sy);
    });

    const endPointer = (event) => {
      const rect = canvas.getBoundingClientRect();
      const sx = event.clientX - rect.left;
      const sy = event.clientY - rect.top;
      const clickedNode = !cortexState.didMove ? (cortexState.dragNode || findNodeAtScreen(sx, sy)) : null;
      cortexState.dragNode = null;
      cortexState.panning = false;
      cortexState.panOrigin = null;
      cortexState.pointerDown = null;
      canvas.classList.remove("is-dragging");
      if (clickedNode) selectCortexNode(clickedNode);
    };

    canvas.addEventListener("pointerup", endPointer);
    canvas.addEventListener("pointercancel", () => {
      cortexState.dragNode = null;
      cortexState.panning = false;
      cortexState.panOrigin = null;
      cortexState.pointerDown = null;
      canvas.classList.remove("is-dragging");
    });
    canvas.addEventListener("pointerleave", () => {
      if (!cortexState.dragNode && !cortexState.panning) {
        cortexState.hoverNode = null;
        canvas.classList.remove("is-hovering");
        updateCortexTooltip(null, 0, 0);
        drawCortexGraph();
      }
    });

    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = event.clientX - rect.left;
      const sy = event.clientY - rect.top;
      const before = screenToWorld(sx, sy);
      const factor = event.deltaY < 0 ? 1.12 : 0.89;
      const nextZoom = Math.max(0.15, Math.min(5, cortexState.camera.zoom * factor));
      cortexState.camera.zoom = nextZoom;
      const after = screenToWorld(sx, sy);
      cortexState.camera.x += before.x - after.x;
      cortexState.camera.y += before.y - after.y;
      drawCortexGraph();
    }, { passive: false });
  }

  elements.cortexSearch?.addEventListener("input", (event) => runCortexSearch(event.target.value));
  elements.cortexModeToggle?.addEventListener("click", () => {
    if (!cortexState.editMode) {
      setCortexEditMode(true);
    } else {
      if (elements.cortexNoteEditor && cortexState.originalContent !== undefined) {
        elements.cortexNoteEditor.value = cortexState.originalContent;
      }
      renderCortexMarkdown(elements.cortexNoteViewer, cortexState.originalContent || "");
      setCortexEditMode(false);
      setCortexStatus("");
    }
  });
  elements.cortexNoteSave?.addEventListener("click", saveCortexNote);
}

function openCortexPage() {
  initCortexCanvasEvents();
  window.requestAnimationFrame(() => {
    resizeCortexCanvas();
    if (!cortexState.nodes.length) {
      loadCortexGraph({ fitOnFirst: true });
    } else {
      ensureCortexLoop();
      drawCortexGraph();
    }
  });
}

// ───────────────────────── MyKOS Swarm (Multi-Agente) ─────────────────────────
const swarmState = {
  data: null,
  pollTimer: 0,
  loading: false,
  initialized: false,
  resizeObserver: null,
  lastRenderSig: "",
  canvasNodes: [],
};

function renderSwarmModelOptions() {
  const select = elements.swarmWorkerModel;
  if (!select) return;
  const previous = select.value || "inherit";
  select.replaceChildren();
  const inheritOpt = document.createElement("option");
  inheritOpt.value = "inherit";
  inheritOpt.textContent = "Usar modelo activo del chat";
  select.appendChild(inheritOpt);
  const grouped = new Map();
  const selectable = (state.models || []).filter((item) => item.chat_capable !== false);
  for (const model of selectable) {
    const provider = model.provider || "other";
    if (!grouped.has(provider)) grouped.set(provider, []);
    grouped.get(provider).push(model);
  }
  for (const [provider, models] of grouped) {
    if (!models.length) continue;
    const group = document.createElement("optgroup");
    group.label = `──── ${providerLabel(provider, models)} ────`;
    for (const model of models) {
      const opt = document.createElement("option");
      opt.value = model.name;
      opt.textContent = `${model.label || model.name}${model.remote ? " · remoto" : " · local"}`;
      group.appendChild(opt);
    }
    select.appendChild(group);
  }
  const stillValid = Array.from(select.options).some((o) => o.value === previous);
  select.value = stillValid ? previous : "inherit";
}

function setSwarmBanner(text, isError = false, action = null) {
  const banner = elements.swarmStatusBanner;
  if (!banner) return;
  if (!text) {
    banner.hidden = true;
    banner.replaceChildren();
    banner.classList.remove("is-error");
    return;
  }
  banner.hidden = false;
  banner.classList.toggle("is-error", isError);
  banner.replaceChildren();
  const msgSpan = document.createElement("span");
  msgSpan.textContent = text;
  banner.appendChild(msgSpan);
  if (action && typeof action.onClick === "function" && action.label) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "swarm-banner-action";
    btn.textContent = action.label;
    btn.addEventListener("click", action.onClick);
    banner.appendChild(btn);
  }
}

async function openSavedSwarmNoteInCortex(relativePath) {
  if (!relativePath) return;
  setPage("cortex");
  await loadCortexGraph({ fitOnFirst: false });
  await loadCortexNote(relativePath);
}

function insertSwarmMention(mentionName) {
  const input = elements.swarmBoardInput;
  if (!input) return;
  const token = `@${String(mentionName || "").replace(/^@/, "")} `;
  const start = typeof input.selectionStart === "number" ? input.selectionStart : input.value.length;
  const end = typeof input.selectionEnd === "number" ? input.selectionEnd : input.value.length;
  const before = input.value.slice(0, start);
  const spacer = before && !/\s$/.test(before) ? " " : "";
  input.value = `${before}${spacer}${token}${input.value.slice(end)}`;
  const cursor = (before + spacer + token).length;
  input.focus();
  input.setSelectionRange(cursor, cursor);
}

function appendHighlightedBoardText(container, text) {
  const raw = String(text || "");
  const tokenRe = /(@[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}|#\d+)/g;
  let lastIndex = 0;
  let match;
  while ((match = tokenRe.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      container.appendChild(document.createTextNode(raw.slice(lastIndex, match.index)));
    }
    const span = document.createElement("span");
    const token = match[0];
    span.className = token.startsWith("@") ? "swarm-ref-mention" : "swarm-ref-seq";
    span.textContent = token;
    container.appendChild(span);
    lastIndex = tokenRe.lastIndex;
  }
  if (lastIndex < raw.length) {
    container.appendChild(document.createTextNode(raw.slice(lastIndex)));
  }
}

function syncSwarmButtonIndicator(data) {
  const btn = elements.openSwarmButton;
  if (!btn) return;
  const workersWorking = Boolean(
    (data?.counts?.working || 0) > 0
    || (data?.member_list || []).some((m) => m.name !== "coordinator" && m.state === "working"),
  );
  btn.classList.toggle("is-working", workersWorking);
}

function stopSwarmPolling() {
  if (swarmState.pollTimer) {
    window.clearTimeout(swarmState.pollTimer);
    swarmState.pollTimer = 0;
  }
}

function scheduleSwarmPollIfNeeded(data = swarmState.data) {
  stopSwarmPolling();
  const pageVisible = Boolean(elements.swarmPage && !elements.swarmPage.hidden);
  const anyWorking = Boolean(
    (data?.counts?.working || 0) > 0
    || (data?.member_list || []).some((m) => m.name !== "coordinator" && m.state === "working"),
  );
  if (!pageVisible && !anyWorking) return;
  swarmState.pollTimer = window.setTimeout(() => {
    swarmState.pollTimer = 0;
    loadSwarmStatus({ schedule: true });
  }, 2500);
}

function renderSwarmRoster(members) {
  const container = elements.swarmRosterList;
  if (!container) return;
  container.replaceChildren();
  for (const m of members) {
    const card = document.createElement("div");
    card.className = `swarm-agent-card ${m.state === "working" ? "is-working" : ""} ${m.state === "killed" ? "is-killed" : ""}`;

    const top = document.createElement("div");
    top.className = "swarm-agent-top";
    const nameEl = document.createElement("span");
    nameEl.className = "swarm-agent-name";
    const dot = document.createElement("span");
    dot.className = `swarm-state-dot ${m.state || "waiting"}`;
    nameEl.appendChild(dot);
    nameEl.appendChild(document.createTextNode(`@${m.name}`));
    const pill = document.createElement("span");
    pill.className = "swarm-state-pill";
    pill.textContent = m.state || "waiting";
    top.appendChild(nameEl);
    top.appendChild(pill);
    card.appendChild(top);

    const meta = document.createElement("div");
    meta.className = "swarm-agent-meta";
    const toolsTxt = `${m.tools_used_count || 0} herr.`;
    meta.textContent = `${m.role || "Especialista"} · ${m.model || "inherit"} · ${toolsTxt}`;
    card.appendChild(meta);

    if (m.last_error) {
      const errEl = document.createElement("div");
      errEl.className = "swarm-agent-error";
      errEl.textContent = m.last_error;
      card.appendChild(errEl);
    }

    const actions = document.createElement("div");
    actions.className = "swarm-agent-actions";
    const mentionBtn = document.createElement("button");
    mentionBtn.type = "button";
    mentionBtn.className = "text-button";
    mentionBtn.textContent = "@Mencionar";
    mentionBtn.addEventListener("click", () => insertSwarmMention(m.name));
    actions.appendChild(mentionBtn);

    if (m.name !== "coordinator") {
      const killBtn = document.createElement("button");
      killBtn.type = "button";
      killBtn.className = "text-button danger-text-button";
      killBtn.textContent = "Detener";
      killBtn.disabled = m.state === "killed";
      killBtn.addEventListener("click", () => killSwarmWorker(m.name));
      actions.appendChild(killBtn);
    }
    card.appendChild(actions);
    container.appendChild(card);
  }
}

function renderSwarmMentionChips(members) {
  const bar = elements.swarmMentionChips;
  if (!bar) return;
  bar.replaceChildren();
  const names = ["all", ...members.filter((m) => m.name !== "coordinator" && m.state !== "killed").map((m) => m.name)];
  for (const name of names) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "swarm-chip-btn";
    btn.textContent = `@${name}`;
    btn.addEventListener("click", () => insertSwarmMention(name));
    bar.appendChild(btn);
  }
}

function renderSwarmBoard(messages) {
  const feed = elements.swarmBoardFeed;
  if (!feed) return;
  const nearBottom = (feed.scrollHeight - feed.scrollTop - feed.clientHeight) < 80;
  feed.replaceChildren();
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "swarm-board-empty";
    empty.textContent = "El tablón está listo. Añade un agente especialista, despliega el equipo rápido o publica una instrucción con @nombre / @all.";
    feed.appendChild(empty);
    return;
  }
  for (const msg of messages) {
    const card = document.createElement("article");
    card.className = `swarm-msg-card ${msg.agent === "coordinator" ? "is-coordinator" : ""}`;

    const header = document.createElement("div");
    header.className = "swarm-msg-header";
    const seqSpan = document.createElement("span");
    seqSpan.className = "swarm-msg-seq";
    seqSpan.textContent = `#${msg.seq}`;
    const authorSpan = document.createElement("span");
    authorSpan.className = "swarm-msg-author";
    authorSpan.textContent = `@${msg.agent}`;
    header.appendChild(seqSpan);
    header.appendChild(authorSpan);
    if (msg.model) {
      const modelChip = document.createElement("span");
      modelChip.className = "swarm-msg-chip";
      modelChip.textContent = msg.model;
      header.appendChild(modelChip);
    }
    if (Number(msg.duration_seconds) > 0) {
      const durChip = document.createElement("span");
      durChip.className = "swarm-msg-chip";
      durChip.textContent = `${Number(msg.duration_seconds).toFixed(1)}s`;
      header.appendChild(durChip);
    }
    const timeSpan = document.createElement("span");
    timeSpan.className = "swarm-msg-time";
    timeSpan.textContent = msg.created_at ? String(msg.created_at).slice(11, 19) : "";
    header.appendChild(timeSpan);
    const saveMsgBtn = document.createElement("button");
    saveMsgBtn.type = "button";
    saveMsgBtn.className = "swarm-msg-save-btn";
    saveMsgBtn.textContent = "Guardar nota en Cortex";
    saveMsgBtn.title = `Guardar mensaje #${msg.seq} en MyKOS Cortex`;
    saveMsgBtn.addEventListener("click", () => saveSwarmToCortex({ seq: msg.seq }));
    header.appendChild(saveMsgBtn);
    card.appendChild(header);

    const body = document.createElement("div");
    body.className = "swarm-msg-body";
    appendHighlightedBoardText(body, msg.text || "");
    card.appendChild(body);

    const tools = Array.isArray(msg.tools_used) ? msg.tools_used : [];
    if (tools.length) {
      const toolsRow = document.createElement("div");
      toolsRow.className = "swarm-msg-tools";
      for (const t of tools) {
        const chip = document.createElement("span");
        chip.className = "swarm-tool-chip";
        chip.textContent = t;
        toolsRow.appendChild(chip);
      }
      card.appendChild(toolsRow);
    }
    feed.appendChild(card);
  }
  if (nearBottom) {
    feed.scrollTop = feed.scrollHeight;
  }
}

function resizeSwarmCanvas() {
  const canvas = elements.swarmCanvas;
  if (!canvas || !canvas.parentElement) return;
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(240, Math.floor(rect.width));
  const h = Math.max(220, Math.floor(rect.height));
  if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
  }
  drawSwarmGraph();
}

function drawSwarmGraph() {
  const canvas = elements.swarmCanvas;
  if (!canvas || !elements.swarmPage || elements.swarmPage.hidden) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.width / dpr;
  const height = canvas.height / dpr;
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const data = swarmState.data;
  const members = Array.isArray(data?.member_list) ? data.member_list : [{ name: "coordinator", state: "waiting" }];
  const edges = Array.isArray(data?.edges) ? data.edges : [];
  const head = Number(data?.head || 0);

  const cx = width / 2;
  const cy = height / 2;
  const workers = members.filter((m) => m.name !== "coordinator");
  const radius = Math.max(60, Math.min(width, height) * 0.34);

  const positions = new Map();
  const nodes = [];
  const coordMember = members.find((m) => m.name === "coordinator") || { name: "coordinator", state: "waiting" };
  const coordPos = { x: cx, y: workers.length ? cy : cy, r: 22, member: coordMember };
  positions.set("coordinator", coordPos);
  nodes.push(coordPos);

  workers.forEach((w, idx) => {
    const angle = (-Math.PI / 2) + (2 * Math.PI * idx) / Math.max(1, workers.length);
    const nx = cx + Math.cos(angle) * radius;
    const ny = cy + Math.sin(angle) * radius;
    const pos = { x: nx, y: ny, r: 17, member: w };
    positions.set(w.name, pos);
    nodes.push(pos);
  });
  swarmState.canvasNodes = nodes;

  for (const edge of edges) {
    const from = positions.get(edge.from);
    const to = positions.get(edge.to);
    if (!from || !to || from === to) continue;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.hypot(dx, dy) || 1;
    const ux = dx / dist;
    const uy = dy / dist;
    const midX = (from.x + to.x) / 2 - uy * 18;
    const midY = (from.y + to.y) / 2 + ux * 18;
    const startX = from.x + ux * (from.r + 3);
    const startY = from.y + uy * (from.r + 3);
    const endX = to.x - ux * (to.r + 6);
    const endY = to.y - uy * (to.r + 6);

    const isLatest = head > 0 && Number(edge.last_seq) === head;
    ctx.beginPath();
    ctx.moveTo(startX, startY);
    ctx.quadraticCurveTo(midX, midY, endX, endY);
    ctx.strokeStyle = isLatest ? "rgba(56, 189, 248, 0.9)" : "rgba(148, 163, 184, 0.42)";
    ctx.lineWidth = isLatest ? 2.4 : Math.min(3, 1.1 + (edge.count || 1) * 0.35);
    ctx.stroke();

    const tangentX = endX - midX;
    const tangentY = endY - midY;
    const tAngle = Math.atan2(tangentY, tangentX);
    ctx.beginPath();
    ctx.moveTo(endX, endY);
    ctx.lineTo(endX - 8 * Math.cos(tAngle - 0.4), endY - 8 * Math.sin(tAngle - 0.4));
    ctx.lineTo(endX - 8 * Math.cos(tAngle + 0.4), endY - 8 * Math.sin(tAngle + 0.4));
    ctx.closePath();
    ctx.fillStyle = isLatest ? "#38bdf8" : "rgba(148, 163, 184, 0.72)";
    ctx.fill();

    if ((edge.count || 0) > 0) {
      ctx.fillStyle = "rgba(15, 23, 34, 0.85)";
      ctx.beginPath();
      ctx.arc(midX, midY, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = isLatest ? "#bae6fd" : "#cbd5e1";
      ctx.font = "600 9.5px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(edge.count), midX, midY);
    }
  }

  const colorFor = (member) => {
    if (member.name === "coordinator") return "#38bdf8";
    if (member.state === "working") return "#f59e0b";
    if (member.state === "killed") return "#64748b";
    return "#22c55e";
  };

  for (const node of nodes) {
    const color = colorFor(node.member);
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(15, 23, 34, 0.94)";
    ctx.fill();
    ctx.lineWidth = node.member.state === "working" ? 3 : 2;
    ctx.strokeStyle = color;
    ctx.stroke();

    ctx.fillStyle = color;
    ctx.font = "700 10px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const shortTag = node.member.name === "coordinator" ? "COORD" : node.member.name.slice(0, 6).toUpperCase();
    ctx.fillText(shortTag, node.x, node.y);

    ctx.fillStyle = node.member.state === "killed" ? "#94a3b8" : "#f1f5f9";
    ctx.font = "600 11px system-ui, sans-serif";
    ctx.textBaseline = "top";
    ctx.fillText(`@${node.member.name}`, node.x, node.y + node.r + 5);
  }
  ctx.restore();
}

function applySwarmData(data) {
  if (!data || typeof data !== "object") return;
  swarmState.data = data;
  syncSwarmButtonIndicator(data);
  if (elements.swarmTitleInput && document.activeElement !== elements.swarmTitleInput) {
    elements.swarmTitleInput.value = data.title || "Swarm MyKOS";
  }
  if (elements.swarmPermissionMode && data.permission_mode) {
    elements.swarmPermissionMode.value = data.permission_mode;
  }
  const counts = data.counts || {};
  if (elements.swarmLiveStats) {
    const totalAgents = counts.members ?? (data.member_list?.length || 1);
    const working = counts.working ?? 0;
    const msgs = counts.messages ?? (data.messages?.length || 0);
    elements.swarmLiveStats.textContent = `${totalAgents} agente${totalAgents === 1 ? "" : "s"} · ${working} trabajando · ${msgs} mensaje${msgs === 1 ? "" : "s"}`;
  }
  const members = Array.isArray(data.member_list) ? data.member_list : [];
  if (elements.swarmRosterCount) elements.swarmRosterCount.textContent = String(members.length);
  if (elements.swarmBoardHead) elements.swarmBoardHead.textContent = `#${data.head || 0}`;

  const renderSig = JSON.stringify({
    h: data.head,
    u: data.updated_at,
    m: members.map((x) => `${x.name}:${x.state}:${x.tools_used_count}:${x.last_error || ""}`),
  });
  if (renderSig !== swarmState.lastRenderSig) {
    swarmState.lastRenderSig = renderSig;
    renderSwarmRoster(members);
    renderSwarmMentionChips(members);
    renderSwarmBoard(Array.isArray(data.messages) ? data.messages : []);
  }
  drawSwarmGraph();
  scheduleSwarmPollIfNeeded(data);
}

async function loadSwarmStatus({ schedule = true } = {}) {
  if (swarmState.loading) return;
  swarmState.loading = true;
  try {
    const data = await api("/api/swarm/status?limit=80");
    setSwarmBanner("");
    applySwarmData(data);
  } catch (error) {
    if (elements.swarmPage && !elements.swarmPage.hidden) {
      setSwarmBanner(error.message || "No se pudo cargar el estado del Swarm.", true);
    }
    if (schedule && elements.swarmPage && !elements.swarmPage.hidden) {
      scheduleSwarmPollIfNeeded(swarmState.data);
    }
  } finally {
    swarmState.loading = false;
  }
}

async function saveSwarmHeaderSettings({ title, permission_mode } = {}) {
  const payload = {};
  if (typeof title === "string" && title.trim()) payload.title = title.trim();
  if (permission_mode) payload.permission_mode = permission_mode;
  if (!Object.keys(payload).length) return;
  try {
    const data = await api("/api/swarm/title", { method: "POST", body: JSON.stringify(payload) });
    setSwarmBanner("");
    applySwarmData(data);
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

async function submitSwarmAddWorker(event) {
  event.preventDefault();
  const name = (elements.swarmWorkerName?.value || "").trim();
  const role = (elements.swarmWorkerRole?.value || "").trim() || "Especialista";
  const brief = (elements.swarmWorkerBrief?.value || "").trim();
  const chosenModel = elements.swarmWorkerModel?.value || "inherit";
  const model = chosenModel === "inherit" ? (selectedModel() || "inherit") : chosenModel;
  if (!name || !brief) return;
  try {
    setSwarmBanner(`Desplegando agente @${name}…`);
    const data = await api("/api/swarm/workers", {
      method: "POST",
      body: JSON.stringify({ name, role, brief, model }),
    });
    if (elements.swarmWorkerName) elements.swarmWorkerName.value = "";
    if (elements.swarmWorkerRole) elements.swarmWorkerRole.value = "";
    if (elements.swarmWorkerBrief) elements.swarmWorkerBrief.value = "";
    setSwarmBanner("");
    applySwarmData(data);
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

const SWARM_TEAM_TEMPLATES = {
  ingenieria: {
    label: "Ingeniería y Código",
    members: [
      {
        name: "investigador",
        role: "Analista de Arquitectura",
        task: "inspecciona el repositorio y la arquitectura relevante con herramientas reales, documenta hallazgos clave y menciona a @implementador para pasar a la fase técnica",
      },
      {
        name: "implementador",
        role: "Ingeniero de Código",
        task: "revisa el análisis previo (#seq), propone o aplica los pasos de código necesarios y menciona a @verificador para validación",
      },
      {
        name: "verificador",
        role: "Especialista QA y Tests",
        task: "ejecuta pruebas/comprobaciones reales sobre los resultados y publica el veredicto final mencionando a @coordinator",
      },
    ],
  },
  seguridad: {
    label: "Auditoría de Seguridad",
    members: [
      {
        name: "red-team",
        role: "Explorador de Superficie y Riesgos",
        task: "mapea superficie de ataque, rutas, endpoints, permisos y vectores potenciales y menciona a @auditor-sec",
      },
      {
        name: "auditor-sec",
        role: "Analista de Código y Políticas",
        task: "audita validaciones, autenticación, HMAC, aislamiento y sanitización sobre los hallazgos previos y menciona a @hardening",
      },
      {
        name: "hardening",
        role: "Verificador de Blindaje",
        task: "prioriza mitigaciones verificables, comprueba controles y entrega el informe de seguridad final a @coordinator",
      },
    ],
  },
  rea: {
    label: "Ingeniería Inversa (REA)",
    members: [
      {
        name: "inspector-rea",
        role: "Analista de Artefactos y Binarios",
        task: "usa herramientas REA (rea_status, rea_list_tools, rea_call_tool) e inspección de archivos para catalogar binarios, bundles o artefactos y menciona a @decompilador",
      },
      {
        name: "decompilador",
        role: "Analista de Flujo y Símbolos",
        task: "analiza símbolos, strings, dependencias y flujos internos identificados y menciona a @relator-rea",
      },
      {
        name: "relator-rea",
        role: "Autor de Informe Técnico",
        task: "consolida la reconstrucción técnica y evidencias verificadas y reporta el informe final a @coordinator",
      },
    ],
  },
  investigacion: {
    label: "Investigación Profunda y Cortex",
    members: [
      {
        name: "explorador-web",
        role: "Investigador Web y Fuentes",
        task: "recopila y contrasta información actualizada y fuentes técnicas verificables y menciona a @analista-cortex",
      },
      {
        name: "analista-cortex",
        role: "Conector de Memoria Cortex",
        task: "consulta MyKOS Cortex (search_cortex / read_cortex_note), cruza el conocimiento previo con los hallazgos nuevos y menciona a @sintetizador",
      },
      {
        name: "sintetizador",
        role: "Redactor de Dossier Ejecutivo",
        task: "redacta el dossier ejecutivo estructurado y accionable con referencias y lo entrega a @coordinator",
      },
    ],
  },
  arquitectura: {
    label: "Consejo de Arquitectura y Rendimiento",
    members: [
      {
        name: "arquitecto",
        role: "Diseñador de Sistemas",
        task: "evalúa el diseño estructural, acoplamiento, escalabilidad y contratos entre componentes y menciona a @critico-perf",
      },
      {
        name: "critico-perf",
        role: "Especialista en Rendimiento/VRAM",
        task: "analiza latencia, concurrencia, I/O, uso de memoria/VRAM y cuellos de botella y menciona a @juez",
      },
      {
        name: "juez",
        role: "Síntesis y Veredicto Final",
        task: "pondera arquitectura vs rendimiento, formula recomendaciones priorizadas y reporta el veredicto final a @coordinator",
      },
    ],
  },
};

async function deployQuickSwarmTeam() {
  const chosenModel = elements.swarmWorkerModel?.value || "inherit";
  const model = chosenModel === "inherit" ? (selectedModel() || "inherit") : chosenModel;
  const titleText = (elements.swarmTitleInput?.value || "").trim() || "Equipo Swarm MyKOS";
  const templateKey = elements.swarmTeamTemplate?.value || "ingenieria";
  const template = SWARM_TEAM_TEMPLATES[templateKey] || SWARM_TEAM_TEMPLATES.ingenieria;
  const [m0, m1, m2] = template.members;

  const firstBrief = (
    `Misión "${titleText}" (${template.label}). Flujo encadenado en 3 fases:\n`
    + `1) Tú (@${m0.name}, ${m0.role}): ${m0.task}.\n`
    + `2) Después @${m1.name} (${m1.role}): ${m1.task}.\n`
    + `3) Finalmente @${m2.name} (${m2.role}): ${m2.task}.\n`
    + `Ejecuta ahora tu Fase 1 con herramientas reales, publica tus hallazgos citando rutas/evidencias y termina mencionando a @${m1.name} con su encargo concreto (recordándole mencionar después a @${m2.name} para el cierre hacia @coordinator).`
  );

  try {
    setSwarmBanner(`Desplegando equipo «${template.label}» (@${m0.name} -> @${m1.name} -> @${m2.name})…`);
    // Registramos primero al #3 y #2 en estado waiting para evitar carreras y lanzar la cadena desde #1.
    await api("/api/swarm/workers", {
      method: "POST",
      body: JSON.stringify({ name: m2.name, role: m2.role, brief: "", model, title: titleText }),
    });
    await api("/api/swarm/workers", {
      method: "POST",
      body: JSON.stringify({ name: m1.name, role: m1.role, brief: "", model, title: titleText }),
    });
    const lastData = await api("/api/swarm/workers", {
      method: "POST",
      body: JSON.stringify({ name: m0.name, role: m0.role, brief: firstBrief, model, title: titleText }),
    });
    setSwarmBanner(`Equipo «${template.label}» desplegado: @${m0.name} iniciado en cadena.`);
    if (lastData) applySwarmData(lastData);
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

async function saveSwarmToCortex({ seq = null } = {}) {
  const titleText = (elements.swarmTitleInput?.value || "").trim();
  const payload = {};
  if (titleText) payload.title = titleText;
  if (Number.isInteger(seq) && seq > 0) payload.seq = seq;
  try {
    setSwarmBanner(seq ? `Guardando mensaje #${seq} en MyKOS Cortex…` : "Compilando y guardando informe del Swarm en MyKOS Cortex…");
    const data = await api("/api/swarm/save-cortex", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const savedPath = data.path || "";
    setSwarmBanner(
      seq ? `Mensaje #${seq} guardado en Cortex: ${savedPath}` : `Informe guardado en Cortex: ${savedPath}`,
      false,
      savedPath ? { label: "Abrir en Cortex", onClick: () => openSavedSwarmNoteInCortex(savedPath) } : null,
    );
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

async function submitSwarmBoardMessage(event) {
  event?.preventDefault();
  const text = (elements.swarmBoardInput?.value || "").trim();
  if (!text) return;
  try {
    const data = await api("/api/swarm/board", {
      method: "POST",
      body: JSON.stringify({ agent: "coordinator", text }),
    });
    if (elements.swarmBoardInput) elements.swarmBoardInput.value = "";
    setSwarmBanner("");
    applySwarmData(data);
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

async function killSwarmWorker(name) {
  try {
    const data = await api("/api/swarm/workers/kill", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setSwarmBanner("");
    applySwarmData(data);
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

async function resetSwarmMission() {
  const nextTitle = (elements.swarmTitleInput?.value || "").trim() || "Nuevo Swarm MyKOS";
  try {
    const data = await api("/api/swarm/reset", {
      method: "POST",
      body: JSON.stringify({ title: nextTitle }),
    });
    if (data.archived_path) {
      setSwarmBanner(
        `Swarm reiniciado. Informe previo auto-archivado en Cortex: ${data.archived_path}`,
        false,
        { label: "Abrir en Cortex", onClick: () => openSavedSwarmNoteInCortex(data.archived_path) },
      );
    } else {
      setSwarmBanner("");
    }
    applySwarmData(data);
  } catch (error) {
    setSwarmBanner(error.message, true);
  }
}

function initSwarmUiEvents() {
  if (swarmState.initialized) return;
  swarmState.initialized = true;
  if (typeof ResizeObserver !== "undefined" && elements.swarmCanvas?.parentElement) {
    swarmState.resizeObserver = new ResizeObserver(() => resizeSwarmCanvas());
    swarmState.resizeObserver.observe(elements.swarmCanvas.parentElement);
  }
  elements.swarmCanvas?.addEventListener("click", (event) => {
    const rect = elements.swarmCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = swarmState.canvasNodes.find((n) => Math.hypot(x - n.x, y - n.y) <= n.r + 6);
    if (hit?.member?.name) insertSwarmMention(hit.member.name);
  });
  elements.swarmTitleSave?.addEventListener("click", () => {
    saveSwarmHeaderSettings({ title: elements.swarmTitleInput?.value });
  });
  elements.swarmTitleInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      saveSwarmHeaderSettings({ title: elements.swarmTitleInput.value });
    }
  });
  elements.swarmPermissionMode?.addEventListener("change", (event) => {
    saveSwarmHeaderSettings({ permission_mode: event.target.value });
  });
  elements.swarmQuickTeam?.addEventListener("click", deployQuickSwarmTeam);
  elements.swarmSaveCortexBtn?.addEventListener("click", () => saveSwarmToCortex());
  elements.swarmResetBtn?.addEventListener("click", resetSwarmMission);
  elements.swarmAddForm?.addEventListener("submit", submitSwarmAddWorker);
  elements.swarmBoardForm?.addEventListener("submit", submitSwarmBoardMessage);
  elements.swarmBoardInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitSwarmBoardMessage();
    }
  });
}

function openSwarmPage() {
  initSwarmUiEvents();
  renderSwarmModelOptions();
  window.requestAnimationFrame(() => {
    resizeSwarmCanvas();
    loadSwarmStatus({ schedule: true });
  });
}


