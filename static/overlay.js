const box = document.getElementById('alert');
const headline = document.getElementById('headline');
const detail = document.getElementById('detail');
const queue = [];
let busy = false;

function play(alert) {
  busy = true;
  box.className = alert.kind;
  headline.textContent = alert.headline;
  detail.textContent = alert.detail || '';
  box.classList.add('show');
  setTimeout(() => {
    box.classList.remove('show');
    setTimeout(() => { busy = false; pump(); }, 600);
  }, 6000);
}

function pump() { if (!busy && queue.length) play(queue.shift()); }

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (event) => {
    let alert;
    try {
      alert = JSON.parse(event.data);
    } catch (err) {
      console.warn('overlay: dropping malformed frame', err);
      return;
    }
    queue.push(alert);
    pump();
  };
  ws.onclose = () => setTimeout(connect, 2000);
}
connect();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { play, pump, connect, queue, isBusy: () => busy };
}
