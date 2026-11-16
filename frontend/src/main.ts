import './style.css';

type Work = { contract_id: string; work_id: string; title: string; status: 'done' | 'planned' | 'cancelled'; price: string; paid: string; remaining: string; excess: string };
type Contract = { contract_id: string; contractor: string; amount: string; active_price: string; discrepancy: string; gross_paid: string; refunded: string; net_paid: string; work_paid: string; unallocated: string; remaining: string; funding_needed: string; excess: string; contract_balance: string };
type Report = { as_of: string; contracts: Contract[]; works: Work[]; warnings: string[] };
const labels = { done: 'Принята', planned: 'Запланирована', cancelled: 'Отменена' };
const dateInput = document.querySelector<HTMLInputElement>('#date')!;
const result = document.querySelector<HTMLElement>('#report')!;
const error = document.querySelector<HTMLElement>('#error')!;
const status = document.querySelector<HTMLElement>('#report-status')!;
const submit = document.querySelector<HTMLButtonElement>('#submit')!;

// No monetary arithmetic or conversion to floating point in the browser.
function rub(value: string): string {
  const [whole, fraction] = value.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')},${fraction}\u00a0₽`;
}
function escape(value: string): string {
  return value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}
function metric(label: string, value: string, note: string, emphasis = false): string {
  return `<div class="metric ${emphasis ? 'accent' : ''}"><span>${label}</span><strong>${rub(value)}</strong><small>${note}</small></div>`;
}
function render(report: Report): void {
  const date = report.as_of.split('-').reverse().join('.');
  const links = [['works', 'Работы'], ['contracts', 'Договоры'], ['allocations', 'Распределение']].map(([table, label]) =>
    `<a class="download" href="/api/csv?date=${encodeURIComponent(report.as_of)}&table=${table}">↓ ${label} · CSV</a>`).join('');
  result.innerHTML = `<div class="section-heading"><div><h2>Отчёт на ${date}</h2><p>Договоров: ${report.contracts.length} · События учтены по эту дату включительно</p></div><div class="downloads">${links}</div></div>` +
    (report.warnings.length ? `<section class="notice"><strong>Требует подтверждения</strong><ul>${report.warnings.map(w => `<li>${escape(w)}</li>`).join('')}</ul></section>` : '') +
    (report.contracts.length ? report.contracts.map(c => {
      const works = report.works.filter(w => w.contract_id === c.contract_id);
      return `<article class="contract"><div class="contract-heading"><div><span class="contract-id">${escape(c.contract_id)}</span><h3>${escape(c.contractor)}</h3></div><span class="contract-total">Сумма договора <b>${rub(c.amount)}</b></span></div>
      <div class="metrics">${metric('Выплачено по договору', c.net_paid, 'После вычета возвратов')}${metric('Свободный аванс', c.unallocated, 'Ещё не распределён по работам')}${metric('Остатки по работам', c.remaining, 'Включая запланированные')}${metric('Нужно перечислить', c.funding_needed, 'Остатки минус свободный аванс', true)}</div>
      <details open><summary>Работы по договору <span>${works.length}</span></summary><div class="table-scroll"><table><thead><tr><th>Работа</th><th>Статус на дату</th><th class="numeric">Цена</th><th class="numeric">Выплачено</th><th class="numeric">Осталось</th></tr></thead><tbody>${works.map(w => `<tr class="${w.status === 'cancelled' ? 'cancelled-row' : ''}"><td><span class="work-id">${escape(w.work_id)}</span>${escape(w.title)}${w.excess !== '0.00' ? `<small class="excess">Целевой излишек: ${rub(w.excess)}</small>` : ''}</td><td><span class="badge ${w.status}">${labels[w.status]}</span></td><td class="numeric">${rub(w.price)}</td><td class="numeric">${rub(w.paid)}</td><td class="numeric">${rub(w.remaining)}</td></tr>`).join('')}</tbody><tfoot><tr><td colspan="2">Итого по действующим работам*</td><td class="numeric">${rub(c.active_price)}</td><td class="numeric">${rub(c.work_paid)}</td><td class="numeric">${rub(c.remaining)}</td></tr></tfoot></table></div></details>
      <div class="reconciliation"><span>Ушло: <b>${rub(c.gross_paid)}</b></span><span>Возвращено: <b>${rub(c.refunded)}</b></span><span>Целевой излишек: <b>${rub(c.excess)}</b></span><span>Баланс от суммы договора: <b>${rub(c.contract_balance)}</b></span></div>
      <p class="footnote">* Отменённые работы исключены из итоговой стоимости. Все целевые выплаты сохранены. Остаток по запланированной работе не означает просрочку.</p></article>`;
    }).join('') : '<div class="empty">На выбранную дату ещё нет подписанных договоров.</div>');
}
async function load(): Promise<void> {
  submit.disabled = true;
  result.hidden = true;
  error.hidden = true;
  status.textContent = 'Читаем данные…';
  try {
    const response = await fetch(`/api/report?date=${encodeURIComponent(dateInput.value)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось построить отчёт');
    render(data as Report);
    result.hidden = false;
    status.textContent = 'Отчёт готов';
  } catch (cause) {
    error.textContent = cause instanceof Error ? cause.message : 'Не удалось загрузить отчёт';
    error.hidden = false;
    status.textContent = 'Ошибка расчёта';
  } finally { submit.disabled = false; }
}
document.querySelector('#report-form')!.addEventListener('submit', event => { event.preventDefault(); void load(); });
void load();
