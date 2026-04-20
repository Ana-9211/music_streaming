// ── STATE ──────────────────────────────────────────────────────────────────
let currentScreen  = 'connect';
let songs          = [];
let songTags       = {};
let queue          = [];
let playlists      = {};
let shuffleOn      = false;
let loopOn         = false;
let isPaused       = false;
let currentVolume  = 70;
let isMuted        = false;
let premuteVolume  = 70;
let demoMode       = true;
let maxChunks      = 200;
let maxTp          = 400;
let addPopupIdx    = null;
let plPickerIdx    = null;

let _lastSong      = '';
let _lastQueue     = '';
let _lastPl        = '';
let _lastLogLen    = 0;
let _lastStatus    = '';
let _lastArtSrc    = '';
let _lastUnderruns = 0;
let _lastConnErr   = '';

// ── UTILS ──────────────────────────────────────────────────────────────────
const fmt    = s => { s = Math.max(0, Math.floor(s)); return Math.floor(s/60) + ':' + String(s%60).padStart(2,'0'); };
const el     = id => document.getElementById(id);
const artUrl = title => {
  const ip = (el('nav-server').textContent || '').split(':')[0];
  return `http://${ip}:9894/art/${encodeURIComponent(title)}`;
};
const genreOf = song => (songTags[song] || {}).genre || '';
const langOf  = song => (songTags[song] || {}).language || '';

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
function escAttr(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function showToast(msg, type = '') {
  const c = el('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast' + (type ? ' toast-' + type : '');
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => { if (t.parentNode) t.remove(); }, 3400);
}

function controlBlocked(msg) {
  showToast(msg, 'warn');
}

window.addEventListener('beforeunload', () => {
  navigator.sendBeacon('/player/stop');
});

// ── SCREEN MANAGEMENT ──────────────────────────────────────────────────────
function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  if (name === 'connect') {
    el('overlay').classList.remove('hidden');
  } else {
    el('overlay').classList.add('hidden');
    const s = el('screen-' + name);
    if (s) s.classList.add('active');
  }
  currentScreen = name;
}

function switchTab(tab) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  el('tab-' + tab).classList.add('active');
  showScreen(tab);
}

function retryConnect() {
  fetch('/player/reset', {method:'POST'});
  el('ip-input').value = '';
  el('c-err').textContent = '';
  el('ip-input').classList.remove('err');
  el('c-btn').disabled = false;
  el('c-btn').textContent = 'Connect';
  showScreen('connect');
}

// ── CONNECT ────────────────────────────────────────────────────────────────
function connect() {
  const ip = el('ip-input').value.trim();
  if (!ip) {
    el('c-err').textContent = 'Enter an IP address.';
    el('ip-input').classList.add('err');
    return;
  }
  el('c-err').textContent = '';
  el('ip-input').classList.remove('err');
  el('c-btn').disabled = true;
  el('c-btn').textContent = 'Connecting…';
  fetch('/player/connect', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ip})
  })
  .then(r => r.json())
  .then(() => { el('c-btn').disabled = false; el('c-btn').textContent = 'Connect'; })
  .catch(() => { el('c-btn').disabled = false; el('c-btn').textContent = 'Connect'; });
}

// ── DEMO MODE ──────────────────────────────────────────────────────────────
function toggleDemoMode() {
  fetch('/player/demo_mode', {method:'POST'})
    .then(r => r.json())
    .then(d => {
      demoMode = d.demo_mode;
      const btn = el('demo-btn');
      btn.textContent = demoMode ? 'DEMO' : 'SMOOTH';
      btn.className = 'nav-demo-btn ' + (demoMode ? 'demo-on' : 'smooth-on');
    });
}

// ── MODALS ──────────────────────────────────────────────────────────────────
function openModal()  { el('modal-bg').classList.remove('hidden'); el('modal-name').value = ''; setTimeout(() => el('modal-name').focus(), 50); }
function closeModal() { el('modal-bg').classList.add('hidden'); }

function createPlaylist() {
  const name = el('modal-name').value.trim();
  if (!name) return;
  fetch('/player/playlist_create', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name})
  }).then(r => r.json()).then(d => { playlists = d.playlists; renderPlaylists(); });
  closeModal();
}

// ── ADD POPUP ───────────────────────────────────────────────────────────────
function showAddPopup(idx, e) {
  e.stopPropagation();
  addPopupIdx = idx;
  const p = el('add-popup');
  p.classList.remove('hidden');
  p.style.left = Math.min(e.clientX, window.innerWidth - 160) + 'px';
  p.style.top  = Math.min(e.clientY, window.innerHeight - 80) + 'px';
}
function closeAddPopup() { el('add-popup').classList.add('hidden'); addPopupIdx = null; }
function addPopupQueue()    { if (addPopupIdx !== null) addToQueue(addPopupIdx);    closeAddPopup(); }
function addPopupPlaylist() { if (addPopupIdx !== null) openPlPicker(addPopupIdx);  closeAddPopup(); }
document.addEventListener('click', e => {
  if (!el('add-popup').classList.contains('hidden') && !e.target.closest('#add-popup'))
    closeAddPopup();
});

// ── PLAYLIST PICKER ─────────────────────────────────────────────────────────
function openPlPicker(idx) {
  plPickerIdx = idx;
  const s = songs[idx];
  const title = s ? s.name.replace(/\.wav$/i, '') : 'this song';
  el('pl-picker-sub').textContent = 'Adding: ' + title;
  renderPlPickerList();
  el('pl-picker-bg').classList.remove('hidden');
}
function renderPlPickerList() {
  const keys = Object.keys(playlists);
  const newRow = `<div class="pl-picker-item new-pl" onclick="plPickerNew()">
    <div><div class="pi-name">+ New Playlist</div><div class="pi-count">Create and add</div></div>
    <span class="pi-plus">✎</span></div>`;
  if (!keys.length) {
    el('pl-picker-list').innerHTML = newRow + '<div style="text-align:center;font-size:12px;color:var(--muted);padding:12px 0">No playlists yet</div>';
  } else {
    el('pl-picker-list').innerHTML = newRow + keys.map(n =>
      `<div class="pl-picker-item" onclick="confirmAddToPl('${escAttr(n)}')">
        <div><div class="pi-name">${esc(n)}</div><div class="pi-count">${(playlists[n]||[]).length} songs</div></div>
        <span class="pi-plus">+</span></div>`
    ).join('');
  }
}
function plPickerNew() {
  const name = prompt('New playlist name:');
  if (!name || !name.trim()) return;
  fetch('/player/playlist_create', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: name.trim()})
  }).then(r => r.json()).then(d => {
    playlists = d.playlists;
    renderPlaylists();
    renderPlPickerList();
    if (plPickerIdx !== null) { addSongToPlaylist(name.trim(), plPickerIdx); closePlPicker(); }
  });
}
function closePlPicker()       { el('pl-picker-bg').classList.add('hidden'); plPickerIdx = null; }
function confirmAddToPl(name)  { if (plPickerIdx !== null) { addSongToPlaylist(name, plPickerIdx); closePlPicker(); } }

// ── CONTROLS ────────────────────────────────────────────────────────────────
let _switchingSong = null; // Track song we're switching to

function playSong(idx) {
  const song = songs[idx];
  if (!song) return;
  const songName = song.name.replace(/\.wav$/i, '');
  _switchingSong = song.name; // Guard poll from overwriting until server catches up

  // Instant visual feedback — loading banner
  const banner = el('switch-banner');
  const switchText = el('switch-text');
  if (banner) {
    switchText.textContent = `Loading "${songName}"…`;
    banner.classList.remove('hidden');
    if (window._bannerTimeout) clearTimeout(window._bannerTimeout);
    window._bannerTimeout = setTimeout(() => {
      if (_switchingSong === song.name) {
        if (banner) banner.classList.add('hidden');
        showToast(`Switch to "${songName}" is taking too long.`, 'warn');
        _switchingSong = null;
      }
    }, 15000);
  }

  // Update nav/playbar immediately
  const chip = el('nav-status');
  chip.className = 'nav-chip buffering';
  chip.textContent = 'Buffering';
  el('pb-sub').textContent = 'loading…';
  el('pb-name').textContent = songName;
  el('pb-cur').textContent = '0:00';
  el('pb-fill').style.width = '0%';

  // Update now-playing center immediately with NEW song info
  el('now-title').textContent = songName;
  const dot = el('status-dot');
  if (dot) { dot.className = 'status-dot buffering'; }
  const stxt = el('status-text');
  if (stxt) { stxt.textContent = 'Buffering'; }
  el('album-art').classList.remove('glow');

  // Show new song's album art immediately
  const artImg = el('art-img');
  const artPh = el('art-ph');
  if (artImg) {
    const url = artUrl(songName);
    artImg.src = url;
    artImg.style.display = 'block';
    if (artPh) artPh.style.display = 'none';
    artImg.onerror = () => { artImg.style.display = 'none'; if (artPh) artPh.style.display = 'flex'; };
    _lastArtSrc = url;
  }

  // Show new song's tags immediately
  const g = genreOf(song.name);
  const l = langOf(song.name);
  let tagsHtml = '';
  if (g) tagsHtml += `<span class="tag tag-genre">${g}</span>`;
  if (l) tagsHtml += `<span class="tag tag-lang">${l}</span>`;
  el('now-tags').innerHTML = tagsHtml;

  fetch('/player/choose', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({choice: idx + 1})
  });
  el('tab-nowplaying').classList.remove('hidden');
  switchTab('nowplaying');
}

function togglePause() {
  if (_lastStatus === 'idle' || _lastStatus === 'ended' || currentScreen === 'connect') {
    controlBlocked('Nothing is playing yet.');
    return;
  }
  fetch('/player/pause', {method:'POST'});
}
function skipSong() {
  if (_lastStatus === 'idle' || _lastStatus === 'ended' || currentScreen === 'connect') {
    controlBlocked('Skip is unavailable until playback starts.');
    return;
  }
  fetch('/player/skip', {method:'POST'});
}
function prevSong() {
  if (_lastStatus === 'idle' || _lastStatus === 'ended' || currentScreen === 'connect') {
    controlBlocked('Previous is unavailable until playback starts.');
    return;
  }
  fetch('/player/prev', {method:'POST'});
}

function toggleLoop() {
  loopOn = !loopOn;
  el('btn-loop').classList.toggle('active', loopOn);
  fetch('/player/loop', {method:'POST'});
}
function toggleShuffle() {
  shuffleOn = !shuffleOn;
  el('btn-shuffle').classList.toggle('active', shuffleOn);
  el('btn-shuffle-pb').classList.toggle('active', shuffleOn);
  fetch('/player/shuffle', {method:'POST'});
}

function updatePlayIcon(paused, status) {
  const playing = !paused && status === 'playing';
  el('icon-pp').innerHTML = playing
    ? '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>'
    : '<path d="M6 4l15 8-15 8V4z"/>';
}

function setVolume(val) {
  currentVolume = parseInt(val);
  if (isMuted && currentVolume > 0) { isMuted = false; fetch('/player/mute', {method:'POST'}); }
  el('vol-slider').value = val;
  updateVolIcon();
  fetch('/player/volume', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({volume: currentVolume / 100})
  });
}
function toggleMute() {
  if (isMuted) { isMuted = false; currentVolume = premuteVolume || 70; }
  else { premuteVolume = currentVolume; isMuted = true; }
  el('vol-slider').value = isMuted ? 0 : currentVolume;
  updateVolIcon();
  fetch('/player/mute', {method:'POST'});
}
function updateVolIcon() {
  const w = el('vol-waves'), ic = el('vol-icon');
  if (isMuted || currentVolume === 0) {
    w.setAttribute('d', 'M23 9l-6 6M17 9l6 6');
    ic.style.color = 'var(--red)';
  } else if (currentVolume < 50) {
    w.setAttribute('d', 'M15.54 8.46a5 5 0 0 1 0 7.07');
    ic.style.color = '';
  } else {
    w.setAttribute('d', 'M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14');
    ic.style.color = '';
  }
}

// ── QUEUE ───────────────────────────────────────────────────────────────────
function addToQueue(idx) {
  fetch('/player/queue_add', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({index: idx})
  }).then(r => r.json()).then(d => { queue = d.queue; renderQueue(); });
}
function removeFromQueue(pos) {
  fetch('/player/queue_remove', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({pos})
  }).then(r => r.json()).then(d => { queue = d.queue; renderQueue(); });
}

// ── PLAYLISTS ───────────────────────────────────────────────────────────────
function addSongToPlaylist(plName, songIdx) {
  fetch('/player/playlist_add_song', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({playlist: plName, song_index: songIdx})
  }).then(r => r.json()).then(d => { playlists = d.playlists; renderPlaylists(); });
}
function removeSongFromPlaylist(plName, pos) {
  fetch('/player/playlist_remove_song', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({playlist: plName, pos})
  }).then(r => r.json()).then(d => { playlists = d.playlists; renderPlaylists(); });
}
function deletePlaylist(name) {
  fetch('/player/playlist_delete', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name})
  }).then(r => r.json()).then(d => { playlists = d.playlists; renderPlaylists(); });
}
function activatePlaylist(name) {
  fetch('/player/playlist_activate', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name})
  }).then(r => r.json()).then(d => {
    queue = d.queue;
    renderQueue();
    renderNpPlaylist(name);
    if (d.first_index != null) playSong(d.first_index);
  });
}

// ── FILTERS ─────────────────────────────────────────────────────────────────
function buildFilterOptions() {
  const genres = new Set(['']);
  const langs  = new Set(['']);
  Object.values(songTags).forEach(t => {
    if (t.genre && t.genre.trim()) genres.add(t.genre.trim());
    if (t.language && t.language.trim()) langs.add(t.language.trim());
  });
  const selG = el('filter-genre');
  const curG = selG.value;
  selG.innerHTML = [...genres].map(v => `<option value="${v}">${v || 'All Genres'}</option>`).join('');
  selG.value = curG;

  const selL = el('filter-lang');
  if (selL) {
    const curL = selL.value;
    selL.innerHTML = [...langs].map(v => `<option value="${v}">${v || 'All Languages'}</option>`).join('');
    selL.value = curL;
  }
}

function applyFilters() { renderLibrary(); }

function filteredSongs() {
  const genre = el('filter-genre').value;
  const lang  = el('filter-lang') ? el('filter-lang').value : '';
  return songs.map((s, i) => ({...s, i})).filter(s => {
    const tags = songTags[s.name] || {};
    if (genre && tags.genre !== genre) return false;
    if (lang  && tags.language !== lang) return false;
    return true;
  });
}

// ── RENDER LIBRARY ──────────────────────────────────────────────────────────
function renderLibrary() {
  const grid = el('song-grid');
  const list = filteredSongs();
  el('lib-count').textContent = list.length + ' track' + (list.length !== 1 ? 's' : '') + ' shown';
  if (!list.length) {
    grid.innerHTML = '<div style="color:var(--muted);padding:16px">No songs match the filter.</div>';
    return;
  }
  grid.innerHTML = list.map(s => {
    const title = s.name.replace(/\.wav$/i, '');
    const genre = genreOf(s.name);
    const lang  = langOf(s.name);
    const genreTag = genre ? `<span class="tag tag-genre">${genre}</span>` : '';
    const langTag  = lang  ? `<span class="tag tag-lang">${lang}</span>` : '';
    return `<div class="song-card">
      <div class="song-art">
        <img src="${artUrl(title)}" onerror="this.style.display='none'"/>
        <div class="song-art-ph">
          <svg width="36" height="36" viewBox="0 0 60 60" fill="none">
            <circle cx="30" cy="30" r="20" stroke="#1DB954" stroke-width="2" stroke-dasharray="5 4"/>
            <circle cx="30" cy="30" r="6"  fill="#1DB954" opacity=".4"/>
          </svg>
        </div>
        <div class="song-hover">
          <button class="icon-btn" onclick="event.stopPropagation();playSong(${s.i})" title="Play">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4l15 8-15 8V4z"/></svg>
          </button>
          <button class="icon-btn" onclick="showAddPopup(${s.i},event)" title="Add" style="background:var(--s3);color:var(--text)">+</button>
        </div>
      </div>
      <div class="song-info">
        <div class="song-name" title="${title}">${title}</div>
        <div class="song-meta">${s.duration ? fmt(s.duration) : ''}</div>
        <div class="song-tags">${genreTag}${langTag}</div>
      </div>
    </div>`;
  }).join('');
}

// ── RENDER PLAYLISTS ────────────────────────────────────────────────────────
function renderPlaylists() {
  const keys = Object.keys(playlists);
  if (!keys.length) {
    el('pl-list').innerHTML = '<div class="pl-empty">No playlists yet.</div>';
    return;
  }
  el('pl-list').innerHTML = keys.map(name => {
    const sl = playlists[name] || [];
    const eName = esc(name);
    const aName = escAttr(name);
    const thumbs = sl.slice(0,4).map(idx => {
      const s = songs[idx];
      const title = s ? s.name.replace(/\.wav$/i, '') : '';
      return `<div class="pl-thumb-cell">${s ? `<img src="${artUrl(title)}" onerror="this.style.display='none'"/>` : ''}</div>`;
    });
    while (thumbs.length < 4) thumbs.push('<div class="pl-thumb-cell"></div>');
    const rows = sl.map((idx, pos) => {
      const s = songs[idx];
      const t = s ? s.name.replace(/\.wav$/i, '') : '?';
      return `<div class="pl-song-row" onclick="playSong(${idx})">
        <span class="pl-song-num">${pos+1}</span>
        <span class="pl-song-name">${t}</span>
        <span class="pl-song-del" onclick="event.stopPropagation();removeSongFromPlaylist('${aName}',${pos})">✕</span>
      </div>`;
    }).join('');
    const safeId = name.replace(/\W/g, '_');
    return `<div class="pl-card">
      <div class="pl-card-head" onclick="togglePlExpand('${safeId}')">
        <div class="pl-thumb">${thumbs.join('')}</div>
        <div class="pl-card-info">
          <div class="pl-card-name">${eName}</div>
          <div class="pl-card-count">${sl.length} song${sl.length!==1?'s':''}</div>
        </div>
        <div class="pl-card-acts" onclick="event.stopPropagation()">
          <button class="pl-act" onclick="activatePlaylist('${aName}')">Play</button>
          <button class="pl-act del" onclick="deletePlaylist('${aName}')">Del</button>
        </div>
      </div>
      <div class="pl-songs" id="pls-${safeId}" style="display:none">
        ${rows || '<div class="pl-empty" style="font-size:11px">Empty playlist.</div>'}
      </div>
    </div>`;
  }).join('');
}
function togglePlExpand(id) {
  const e = el('pls-' + id);
  if (e) e.style.display = e.style.display === 'none' ? 'block' : 'none';
}

// ── RENDER NOW PLAYING LEFT PANEL ───────────────────────────────────────────
function renderNpPlaylist(activePl) {
  el('np-pl-name').textContent = activePl || 'None';
  const sl = (activePl && playlists[activePl]) ? playlists[activePl] : [];
  const rows = sl.map((idx, pos) => {
    const s = songs[idx];
    const t = s ? s.name.replace(/\.wav$/i, '') : '?';
    return `<div class="np-row" onclick="playSong(${idx})">
      <span class="np-row-num">${pos+1}</span>
      <span class="np-row-name">${t}</span>
    </div>`;
  }).join('');
  const qRows = queue.length
    ? '<div class="np-sec-label">Queue</div>' + queue.map((idx, pos) => {
        const s = songs[idx];
        const t = s ? s.name.replace(/\.wav$/i, '') : '?';
        return `<div class="np-row" onclick="playSong(${idx})" style="opacity:.7">
          <span class="np-row-num" style="color:var(--accent)">+</span>
          <span class="np-row-name">${t}</span>
        </div>`;
      }).join('')
    : '';
  el('np-pl-list').innerHTML = rows + qRows || '<div class="np-empty">No songs.</div>';
}

// ── RENDER QUEUE ────────────────────────────────────────────────────────────
function renderQueue() {
  const qi = el('queue-items');
  const pb = el('pb-upnext');
  if (!queue.length) {
    qi.innerHTML = '<div class="q-empty">Queue empty.</div>';
    pb.textContent = '—';
    return;
  }
  qi.innerHTML = queue.map((idx, pos) => {
    const t = songs[idx] ? songs[idx].name.replace(/\.wav$/i, '') : '?';
    return `<div class="q-item">
      <span class="q-num">${pos+1}</span>
      <span class="q-name">${t}</span>
      <span class="q-del" onclick="removeFromQueue(${pos})">✕</span>
    </div>`;
  }).join('');
  pb.textContent = songs[queue[0]] ? songs[queue[0]].name.replace(/\.wav$/i, '') : '—';
}

// ── POLL ────────────────────────────────────────────────────────────────────
function poll() {
  fetch('/player/state')
    .then(r => r.json())
    .then(s => {

      // Detect if server has caught up to our song switch
      const switching = _switchingSong && s.song !== _switchingSong;
      if (_switchingSong && s.song === _switchingSong) {
        _switchingSong = null;
      }

      el('nav-server').textContent = s.server_ip || 'Not connected';
      if (!switching) {
        const chip = el('nav-status');
        chip.className   = 'nav-chip ' + (s.status || 'idle');
        chip.textContent = s.status ? s.status.charAt(0).toUpperCase() + s.status.slice(1) : 'Idle';
      }

      if (s.demo_mode !== demoMode) {
        demoMode = s.demo_mode;
        const btn = el('demo-btn');
        btn.textContent = demoMode ? 'DEMO' : 'SMOOTH';
        btn.className   = 'nav-demo-btn ' + (demoMode ? 'demo-on' : 'smooth-on');
      }

      if (s.connect_error && currentScreen === 'connect') {
        el('c-err').textContent = s.connect_error;
        el('ip-input').classList.add('err');
        el('c-btn').disabled    = false;
        el('c-btn').textContent = 'Connect';
        if (s.connect_error !== _lastConnErr) {
          showToast('Connection failed', 'error');
          _lastConnErr = s.connect_error;
        }
      } else {
        _lastConnErr = '';
      }

      if (s.screen === 'error' && currentScreen !== 'error') {
        el('err-title').textContent   = 'Connection Error';
        el('err-msg').textContent     = s.error_msg || 'An error occurred.';
        el('err-retry').style.display = '';
        showScreen('error');
      } else if (s.screen === 'connect' && currentScreen !== 'connect' && !s.connecting) {
        showScreen('connect');
        el('tab-nowplaying').classList.add('hidden');
        _lastSong = ''; _lastQueue = ''; _lastPl = ''; _lastUnderruns = 0; _switchingSong = null;
      } else if ((s.screen === 'library' || s.screen === 'nowplaying') && currentScreen === 'connect') {
        if (s.song_started) {
          showScreen('nowplaying');
          el('tab-nowplaying').classList.remove('hidden');
          el('tab-library').classList.remove('active');
          el('tab-nowplaying').classList.add('active');
        } else {
          showScreen('library');
          el('tab-library').classList.add('active');
        }
      }

      if (s.song_started) el('tab-nowplaying').classList.remove('hidden');

      const sj = JSON.stringify((s.songs || []).map(x => x.name));
      if (sj !== _lastSong) {
        songs     = s.songs || [];
        _lastSong = sj;
        songTags  = s.song_tags || {};
        buildFilterOptions();
        renderLibrary();
        renderPlaylists();
      }

      if (s.song_tags && JSON.stringify(s.song_tags) !== JSON.stringify(songTags)) {
        songTags = s.song_tags;
        buildFilterOptions();
        renderLibrary();
      }

      const qj = JSON.stringify(s.queue || []);
      if (qj !== _lastQueue) {
        queue      = s.queue || [];
        _lastQueue = qj;
        renderQueue();
        renderNpPlaylist(s.active_playlist);
      }

      const plj = JSON.stringify(s.playlists || {});
      if (plj !== _lastPl) {
        playlists = s.playlists || {};
        _lastPl   = plj;
        renderPlaylists();
        renderNpPlaylist(s.active_playlist);
      }

      if (s.loop !== loopOn)       { loopOn = s.loop; el('btn-loop').classList.toggle('active', loopOn); }
      if (s.shuffle !== shuffleOn) {
        shuffleOn = s.shuffle;
        el('btn-shuffle').classList.toggle('active', shuffleOn);
        el('btn-shuffle-pb').classList.toggle('active', shuffleOn);
      }
      if (!switching && (s.paused !== isPaused || s.status !== _lastStatus)) {
        isPaused    = s.paused;
        _lastStatus = s.status;
        updatePlayIcon(s.paused, s.status);
      }
      if (s.muted !== undefined && s.muted !== isMuted) {
        isMuted = s.muted;
        el('vol-slider').value = isMuted ? 0 : currentVolume;
        updateVolIcon();
      }

      if ((s.logs || []).length !== _lastLogLen) {
        _lastLogLen = (s.logs || []).length;
        el('np-log').innerHTML = [...(s.logs || [])].reverse().map(l => {
          const cls = l.includes('error') || l.includes('Error') ? 'log-err'
                    : l.includes('warn')  || l.includes('underrun') ? 'log-warn' : 'log-ok';
          return `<div class="${cls}">${l}</div>`;
        }).join('');
      }

      if (!switching) {
        const pbTitle = (s.song || 'Nothing playing').replace(/\.wav$/i, '');
        el('pb-name').textContent = pbTitle;
        el('pb-sub').textContent  = s.status === 'playing'   ? 'playing'
                                  : s.status === 'paused'    ? 'paused'
                                  : s.status === 'buffering' ? 'buffering…'
                                  : s.song ? s.status : '—';
        const pct = s.duration > 0 ? Math.min(100, (s.progress / s.duration) * 100) : 0;
        el('pb-fill').style.width = pct.toFixed(2) + '%';
        el('pb-cur').textContent  = fmt(s.progress);
        el('pb-dur').textContent  = fmt(s.duration);
      }

      if (currentScreen === 'nowplaying') {

        if (!switching) {
          const title = (s.song || 'No song selected').replace(/\.wav$/i, '');
          el('now-title').textContent = title;

          const g = (songTags[s.song] || {}).genre || '';
          const l = (songTags[s.song] || {}).language || '';
          let tagsHtml = '';
          if (g) tagsHtml += `<span class="tag tag-genre">${g}</span>`;
          if (l) tagsHtml += `<span class="tag tag-lang">${l}</span>`;
          el('now-tags').innerHTML = tagsHtml;

          if (s.song && s.server_ip) {
            const url = artUrl(title);
            if (url !== _lastArtSrc) {
              _lastArtSrc = url;
              const img = el('art-img');
              img.src = url;
              img.style.display = 'block';
              el('art-ph').style.display = 'none';
              img.onerror = () => { img.style.display = 'none'; el('art-ph').style.display = 'flex'; };
            }
          }
          el('album-art').classList.toggle('glow', s.status === 'playing');
        }

        // Hide switch banner only when server confirms the NEW song
        const banner = el('switch-banner');
        if (banner && !switching && (s.status === 'playing' || s.status === 'paused' || s.status === 'ended' || s.status === 'idle')) {
          banner.classList.add('hidden');
        }

        if (!switching) {
          const dot = el('status-dot');
          dot.className = 'status-dot' + (s.status === 'playing'   ? ' playing'
                                         : s.status === 'buffering' ? ' buffering'
                                         : s.status === 'paused'    ? ' paused'
                                         : s.status === 'error'     ? ' error' : '');
          el('status-text').textContent = {
            playing:'Playing', buffering:'Buffering', paused:'Paused',
            ended:'Ended', idle:'Ready', error:'Error'
          }[s.status] || s.status;
        }

        const c = s.chunks || 0;
        if (c > maxChunks) maxChunks = c;
        el('s-chunks').textContent = c;
        el('b-chunks').style.width = Math.min(100, (c / maxChunks) * 100).toFixed(1) + '%';
        el('s-lat').textContent    = (s.avg_latency || 0).toFixed(1);
        el('s-ur').textContent     = s.underruns || 0;
        if ((s.underruns || 0) > _lastUnderruns && _lastUnderruns >= 0) {
          showToast(`Buffer underrun #${s.underruns}`, 'warn');
        }
        _lastUnderruns = s.underruns || 0;
        const tp = s.throughput || 0;
        if (tp > maxTp) maxTp = tp;
        el('s-tp').textContent     = tp.toFixed(1);
        el('b-tp').style.width     = Math.min(100, (tp / maxTp) * 100).toFixed(1) + '%';

        el('mini-chart').innerHTML = (s.buffer_history || []).slice(-20).map(v => {
          const r = Math.min(1, v / 20);
          const h = Math.max(3, Math.round(r * 36));
          const col = r > .6 ? 'var(--green)' : r > .3 ? 'var(--amber)' : 'var(--red)';
          return `<div class="mini-bar" style="height:${h}px;background:${col}"></div>`;
        }).join('');

        el('hist-list').innerHTML = [...(s.history || [])].reverse().slice(0, 4).map(h =>
          `<div class="hist-card">
            <div class="hist-song">${h.song.replace(/\.wav$/i, '')}</div>
            <div class="hist-meta"><b>${h.duration}s</b> · <b>${h.chunks}</b> chunks · <b>${h.throughput}</b> KB/s</div>
          </div>`
        ).join('');

        renderNpPlaylist(s.active_playlist);
      }
    })
    .catch(() => {
      if (currentScreen !== 'error' && currentScreen !== 'connect') {
        el('err-title').textContent   = 'Connection Lost';
        el('err-msg').textContent     = 'Player backend stopped. Restart client.py.';
        el('err-retry').style.display = 'none';
        showScreen('error');
      }
    });

  setTimeout(poll, currentScreen === 'connect' ? 400 : 800);
}

poll();
