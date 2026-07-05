const state = {
  workspaces: [],
};

const els = {
  apiBadge: document.getElementById('api-badge'),
  refreshBtn: document.getElementById('refresh-btn'),
  createBtn: document.getElementById('create-btn'),
  userId: document.getElementById('user-id'),
  totalCount: document.getElementById('total-count'),
  runningCount: document.getElementById('running-count'),
  stoppedCount: document.getElementById('stopped-count'),
  deletedCount: document.getElementById('deleted-count'),
  grid: document.getElementById('workspace-grid'),
  deletedGrid: document.getElementById('deleted-grid'),
  message: document.getElementById('message'),
};

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function showMessage(text, type = 'success') {
  els.message.hidden = false;
  els.message.className = `alert alert--${type}`;
  els.message.textContent = text;
}

function hideMessage() {
  els.message.hidden = true;
  els.message.textContent = '';
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  const bodyText = await response.text();
  let body = null;
  if (bodyText) {
    try {
      body = JSON.parse(bodyText);
    } catch {
      body = { detail: bodyText };
    }
  }

  if (!response.ok) {
    const message = body?.detail || `Request failed (${response.status})`;
    throw new Error(message);
  }

  return body;
}

async function request(path, options = {}) {
  return api(path, options);
}

function updateStats() {
  const total = state.workspaces.length;
  const running = state.workspaces.filter((workspace) => workspace.status === 'running').length;
  const stopped = state.workspaces.filter((workspace) => workspace.status === 'stopped').length;
  const deleted = state.workspaces.filter((workspace) => workspace.status === 'deleted').length;

  els.totalCount.textContent = String(total);
  els.runningCount.textContent = String(running);
  els.stoppedCount.textContent = String(stopped);
  els.deletedCount.textContent = String(deleted);
}

function workspaceStatusClass(status) {
  if (status === 'running') return 'status-badge--online';
  if (status === 'stopped') return 'status-badge--offline';
  if (status === 'deleted') return 'status-badge--deleted';
  return 'status-badge--offline';
}

function renderWorkspace(workspace) {
  const card = document.createElement('article');
  card.className = `workspace-card workspace-card--${workspace.status}`;

  const top = document.createElement('div');
  top.className = 'workspace-card__top';
  top.innerHTML = `
    <div>
      <p class="eyebrow">Workspace</p>
      <h3>${workspace.user_id}</h3>
    </div>
    <span class="status-badge ${workspaceStatusClass(workspace.status)}">${workspace.status}</span>
  `;

  const meta = document.createElement('div');
  meta.className = 'workspace-meta';
  meta.innerHTML = `
    <span><strong>ID</strong>${workspace.id}</span>
    <span><strong>Port</strong>${workspace.port ?? 'pending'}</span>
    <span><strong>Created</strong>${formatDate(workspace.created_at)}</span>
    <span><strong>Last active</strong>${formatDate(workspace.last_active)}</span>
  `;

  const link = document.createElement('div');
  link.className = 'workspace-link';
  link.innerHTML = `
    <div>
      <strong>Browser IDE</strong>
      <p>${workspace.status === 'deleted' ? 'Workspace is in Deleted and can be restored or purged.' : workspace.url ?? 'URL will appear after workspace starts'}</p>
    </div>
  `;

  const linkButton = document.createElement('button');
  linkButton.className = 'mini-button';
  linkButton.textContent = 'Copy URL';
  linkButton.disabled = !workspace.url || workspace.status === 'deleted';
  linkButton.addEventListener('click', async () => {
    if (!workspace.url) return;
    await navigator.clipboard.writeText(workspace.url);
    showMessage('Workspace URL copied to clipboard.', 'success');
  });
  link.appendChild(linkButton);

  const actions = document.createElement('div');
  actions.className = 'workspace-actions';

  const openButton = document.createElement('button');
  openButton.className = 'secondary-button';
  openButton.textContent = 'Open IDE';
  openButton.disabled = !workspace.url || workspace.status === 'deleted';
  openButton.addEventListener('click', () => {
    if (workspace.url) {
      window.open(workspace.url, '_blank', 'noopener,noreferrer');
    }
  });

  const toggleButton = document.createElement('button');
  toggleButton.className = workspace.status === 'deleted' ? 'primary-button' : 'secondary-button';
  toggleButton.textContent = workspace.status === 'running' ? 'Stop' : workspace.status === 'deleted' ? 'Restore' : 'Start';
  toggleButton.addEventListener('click', async () => {
    await performAction(workspace.id, workspace.status === 'running' ? 'stop' : 'start');
  });

  const heartbeatButton = document.createElement('button');
  heartbeatButton.className = 'secondary-button';
  heartbeatButton.textContent = 'Heartbeat';
  heartbeatButton.disabled = workspace.status === 'deleted';
  heartbeatButton.addEventListener('click', async () => {
    await performAction(workspace.id, 'heartbeat');
  });

  const deleteButton = document.createElement('button');
  deleteButton.className = 'danger-button';
  deleteButton.textContent = 'Move to Deleted';
  deleteButton.disabled = workspace.status === 'deleted';
  deleteButton.addEventListener('click', async () => {
    if (!window.confirm('Move this workspace to Deleted and keep its files?')) return;
    await performAction(workspace.id, 'delete');
  });

  const purgeButton = document.createElement('button');
  purgeButton.className = 'danger-button';
  purgeButton.textContent = 'Purge data';
  purgeButton.disabled = workspace.status !== 'deleted';
  purgeButton.addEventListener('click', async () => {
    if (!window.confirm('Purge this workspace and remove stored files permanently?')) return;
    await performAction(workspace.id, 'purge');
  });

  actions.append(openButton, toggleButton, heartbeatButton, deleteButton, purgeButton);
  card.append(top, meta, link, actions);
  return card;
}

function renderWorkspaces() {
  els.grid.innerHTML = '';
  els.deletedGrid.innerHTML = '';

  const active = state.workspaces.filter((workspace) => workspace.status !== 'deleted');
  const deleted = state.workspaces.filter((workspace) => workspace.status === 'deleted');

  if (active.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = '<h3>No workspaces yet</h3><p>Create the first environment and it will appear here with live controls.</p>';
    els.grid.appendChild(empty);
  } else {
    active.forEach((workspace) => {
      els.grid.appendChild(renderWorkspace(workspace));
    });
  }

  if (deleted.length === 0) {
    const emptyDeleted = document.createElement('div');
    emptyDeleted.className = 'empty-state empty-state--compact';
    emptyDeleted.innerHTML = '<h3>No deleted workspaces</h3><p>Moved workspaces will appear here until you purge them.</p>';
    els.deletedGrid.appendChild(emptyDeleted);
  } else {
    deleted.forEach((workspace) => {
      els.deletedGrid.appendChild(renderWorkspace(workspace));
    });
  }
}

async function loadWorkspaces(silent = false) {
  if (!silent) {
    els.refreshBtn.disabled = true;
    els.refreshBtn.textContent = 'Refreshing...';
  }

  try {
    const [health, workspaces] = await Promise.all([request('/health'), api('/api/workspaces')]);
    state.workspaces = workspaces;
    els.apiBadge.textContent = health.ok ? 'API online' : 'API unavailable';
    els.apiBadge.className = `status-badge ${health.ok ? 'status-badge--online' : 'status-badge--offline'}`;
    updateStats();
    renderWorkspaces();
    hideMessage();
  } catch (error) {
    els.apiBadge.textContent = 'API offline';
    els.apiBadge.className = 'status-badge status-badge--offline';
    showMessage(error.message, 'error');
  } finally {
    if (!silent) {
      els.refreshBtn.disabled = false;
      els.refreshBtn.textContent = 'Refresh';
    }
  }
}

async function performAction(workspaceId, action) {
  try {
    if (action === 'start') {
      await api(`/api/workspaces/${workspaceId}/start`, { method: 'POST' });
      showMessage('Workspace started.', 'success');
    } else if (action === 'stop') {
      await api(`/api/workspaces/${workspaceId}/stop`, { method: 'POST' });
      showMessage('Workspace stopped.', 'success');
    } else if (action === 'heartbeat') {
      await api(`/api/workspaces/${workspaceId}/heartbeat`, { method: 'POST' });
      showMessage('Workspace marked active.', 'success');
    } else if (action === 'delete') {
      await api(`/api/workspaces/${workspaceId}`, { method: 'DELETE' });
      showMessage('Workspace moved to Deleted. Files are kept.', 'success');
    } else {
      await api(`/api/workspaces/${workspaceId}?purge=true`, { method: 'DELETE' });
      showMessage('Workspace deleted and data purged.', 'success');
    }

    await loadWorkspaces(true);
  } catch (error) {
    showMessage(error.message, 'error');
  }
}

async function createWorkspace() {
  const userId = els.userId.value.trim();
  if (!userId) {
    showMessage('Enter a workspace name or user id first.', 'error');
    return;
  }

  els.createBtn.disabled = true;
  els.createBtn.textContent = 'Creating...';

  try {
    await api('/api/workspaces', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    });

    showMessage(`Workspace created for ${userId}.`, 'success');
    await loadWorkspaces(true);
  } catch (error) {
    showMessage(error.message, 'error');
  } finally {
    els.createBtn.disabled = false;
    els.createBtn.textContent = 'Create workspace';
  }
}

els.refreshBtn.addEventListener('click', () => loadWorkspaces());
els.createBtn.addEventListener('click', () => createWorkspace());
els.userId.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    createWorkspace();
  }
});

loadWorkspaces();
setInterval(() => loadWorkspaces(true), 15000);