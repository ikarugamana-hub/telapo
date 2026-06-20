function formatNumber(value) {
    return new Intl.NumberFormat('ja-JP').format(value || 0);
}

function renderProgress(data) {
    const panel = document.querySelector('[data-progress-panel]');
    if (!panel) return;

    const latest = data.latest || {};
    const latestText = latest.prefecture
        ? `最新登録: ${latest.prefecture}${latest.municipality ? ' / ' + latest.municipality : ''}`
        : '最新登録: まだありません';

    document.querySelector('[data-progress-current]').textContent = latestText;
    const description = document.querySelector('[data-progress-description]');
    if (description) {
        description.textContent = data.description || '';
    }
    document.querySelector('[data-progress-updated]').textContent =
        `自動更新 ${new Date().toLocaleTimeString('ja-JP')}`;
    document.querySelector('[data-progress-total]').textContent =
        `対象合計 ${formatNumber(data.total)} / ${formatNumber(data.target_total)} 件 (${data.overall_percent}%)`;
    document.querySelector('[data-progress-prefectures]').textContent =
        `達成 ${data.completed_targets} / ${data.target_count} 収集目標`;

    const bar = document.querySelector('[data-progress-bar]');
    bar.style.width = `${Math.min(data.overall_percent, 100)}%`;

    const grid = document.querySelector('[data-progress-grid]');
    grid.innerHTML = '';
    data.prefectures.forEach(pref => {
        const item = document.createElement('div');
        item.className = `progress-prefecture${pref.completed ? ' completed' : ''}`;
        if (latest.prefecture === pref.name || (pref.members || []).includes(latest.prefecture)) {
            item.classList.add('active');
        }

        const name = document.createElement('strong');
        name.textContent = pref.name;

        const count = document.createElement('span');
        count.textContent = `${formatNumber(pref.count)} / ${formatNumber(pref.target)}件`;

        const detail = document.createElement('span');
        detail.textContent = `追加 ${formatNumber(pref.added)}件 / 残り ${formatNumber(pref.remaining)}件`;

        const meter = document.createElement('div');
        meter.className = 'progress-mini-bar';
        const meterFill = document.createElement('div');
        meterFill.style.width = `${Math.min(pref.percent, 100)}%`;
        meter.appendChild(meterFill);

        item.append(name, count, detail, meter);
        grid.appendChild(item);
    });
}

function loadProgress() {
    fetch('/api/progress')
        .then(res => res.json())
        .then(renderProgress)
        .catch(() => {
            const current = document.querySelector('[data-progress-current]');
            if (current) current.textContent = '進捗を取得できませんでした';
        });
}

loadProgress();
setInterval(loadProgress, 10000);
