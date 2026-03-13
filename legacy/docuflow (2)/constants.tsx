import React from 'react';
import { Contract, ContractStatus, ContractType, Counterparty, Invoice, Template } from './types';

// --- Icons (Inline SVGs to avoid dependencies) ---

export const Icons = {
  Dashboard: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><rect width="7" height="9" x="3" y="3" rx="1" /><rect width="7" height="5" x="14" y="3" rx="1" /><rect width="7" height="9" x="14" y="12" rx="1" /><rect width="7" height="5" x="3" y="16" rx="1" /></svg>
  ),
  FileText: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /></svg>
  ),
  Users: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
  ),
  Receipt: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z" /><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8" /><path d="M12 17V7" /></svg>
  ),
  Settings: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.47a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.39a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></svg>
  ),
  Plus: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M5 12h14" /><path d="M12 5v14" /></svg>
  ),
  Download: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></svg>
  ),
  ChevronRight: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="m9 18 6-6-6-6" /></svg>
  ),
  Check: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><polyline points="20 6 9 17 4 12" /></svg>
  ),
  Menu: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><line x1="4" x2="20" y1="12" y2="12" /><line x1="4" x2="20" y1="6" y2="6" /><line x1="4" x2="20" y1="18" y2="18" /></svg>
  ),
  X: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
  ),
  Search: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
  ),
  Printer: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><polyline points="6 9 6 2 18 2 18 9" /><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" /><rect width="12" height="8" x="6" y="14" /></svg>
  ),
  Trash: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /></svg>
  ),
  Edit: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" /></svg>
  ),
  Upload: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" x2="12" y1="3" y2="15" /></svg>
  ),
  Save: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v13a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" /></svg>
  ),
  Sun: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" /></svg>
  ),
  Moon: (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" /></svg>
  )
};

// --- Mock Data ---

export const MOCK_COUNTERPARTIES: Counterparty[] = [
  { id: '1', name: 'ООО "ТехноСолюшнс"', inn: '7701234567', address: '123000, г. Москва, ул. Инновационная, д. 1', contactPerson: 'Иванов Иван', email: 'ivanov@techsol.ru' },
  { id: '2', name: 'АО "Глобал Логистик"', inn: '7709876543', address: '190000, г. Санкт-Петербург, Невский пр-т, д. 45', contactPerson: 'Смирнова Анна', email: 'smirnova@globallog.ru' },
  { id: '3', name: 'ИП Петров П.П.', inn: '5029384756', address: '141400, г. Химки, ул. Ленина, д. 5', contactPerson: 'Петров Петр', email: 'petrov@design.ru' },
];

export const MOCK_INVOICES: Invoice[] = [
  {
    id: 'inv-001', number: 'СЧ-2023-001', date: '25.10.2023', amount: 500000, currency: 'RUB', status: 'Не оплачен',
    items: [{ id: 'i1', description: 'Разработка веб-сайта (этап 1)', quantity: 1, price: 500000, unit: 'Проект' }]
  },
  {
    id: 'inv-002', number: 'СЧ-2023-002', date: '26.10.2023', amount: 120000, currency: 'RUB', status: 'Оплачен',
    items: [
        { id: 'i2', description: 'Техническая поддержка серверов', quantity: 12, price: 10000, unit: 'Час' }
    ]
  },
  {
    id: 'inv-003', number: 'СЧ-2023-003', date: '27.10.2023', amount: 85000, currency: 'RUB', status: 'Не оплачен',
    items: [
        { id: 'i3', description: 'Консультационные услуги', quantity: 5, price: 17000, unit: 'Час' }
    ]
  },
];

const MOCK_TEMPLATE_CONTENT = '<div class="document-page"><h1>{{contract_type}} № {{contract_number}}</h1></div>';
const MOCK_SUPPLY_WITH_VAT_TEMPLATE_CONTENT = `
<div class="document-page">
  <h1>ДОГОВОР ПОСТАВКИ № {{contract_number}}</h1>
  <p>г. {{city}} {{created_date_long}}</p>
  <p>
    Поставщик: {{supplier_name}}. Покупатель: {{buyer_name}}.
    Стороны заключили настоящий договор поставки.
  </p>
  <p>
    Общая стоимость товара: <strong>{{total_amount_formatted}}</strong>.
    НДС: <strong>{{vat_rate}}%</strong> (режим {{vat_mode}}).
  </p>
  <p>Оплата: {{payment_terms}} календарных дней.</p>
</div>`;
const MOCK_GOODS_SALE_EXTENDED_CONFIDENTIALITY_TEMPLATE_CONTENT = `
<div class="document-page contract-snapshot">
  <h1>
    ДОГОВОР КУПЛИ-ПРОДАЖИ ТОВАРА № {{contract_number}}
  </h1>
  <div class="doc-meta">
    <span>г. {{city}}</span>
    <span>{{created_date_long}}</span>
  </div>
  <p>
    Индивидуальный предприниматель {{supplier_name}}, ОГРНИП {{supplier_registration_number}},
    ИНН {{supplier_inn}}, адрес регистрации: {{supplier_address}}, тел.: {{supplier_phone}},
    e-mail: {{supplier_email}}, именуемый далее «Продавец», с одной стороны, и {{buyer_name}},
    паспорт: [серия, номер], выдан [кем, когда], адрес: {{buyer_address}}, тел.: [____],
    e-mail: {{buyer_email}}, именуемый далее «Покупатель», с другой стороны, совместно именуемые
    «Стороны», заключили настоящий договор (далее — «Договор») о нижеследующем.
  </p>
  <h2>1. Предмет договора</h2>
  <p>1.1. Продавец обязуется передать в собственность Покупателю товар, указанный в Приложении №1 (Спецификация), а Покупатель обязуется принять Товар и оплатить его на условиях Договора.</p>
  <p>1.2. Спецификация (Приложение №1) является неотъемлемой частью Договора.</p>
  <h2>2. Цена, налоги, общая сумма</h2>
  <p>2.1. Общая стоимость Товара по Договору составляет: <strong>{{total_amount_formatted}} руб.</strong> ([сумма прописью]) руб. 00 коп.</p>
  <p>2.2. Цена фиксирована и не подлежит одностороннему изменению Продавцом.</p>
  <p>2.3. Налоги/НДС: — если Продавец выставляет НДС: [указать ставку/сумму]; — если НДС не применяется: [указать основание/режим].</p>
  <h2>3. Порядок расчетов</h2>
  <p>3.1. Оплата производится в размере 100% предоплаты, если иное не согласовано письменно.</p>
  <p>3.2. Срок оплаты: в течение 3 (трёх) рабочих дней с даты подписания Договора.</p>
  <p>3.3. Обязательство по оплате считается исполненным в дату зачисления денежных средств на банковский счет Продавца (в т.ч. СБП/переводом).</p>
  <p>3.4. Реквизиты для оплаты указаны в разделе 14.</p>
  <p>3.5. При ошибках в реквизитах/назначении платежа Покупатель обязан немедленно уведомить Продавца; риск задержки исполнения в таком случае несёт Покупатель.</p>
  <p>3.6. Рекомендуемое назначение платежа (комментарий к переводу): «Оплата по договору №{{contract_number}} от {{created_date}} за товар по спецификации».</p>
  <h2>4. Сроки поставки, доставка</h2>
  <p>4.1. Срок передачи Товара Покупателю: не позднее 35 (тридцати пяти) календарных дней с даты поступления полной оплаты.</p>
  <p>4.2. Город передачи/доставки: г. Челябинск (если иной — указывается в переписке/допсоглашении).</p>
  <p>4.3. Доставка осуществляется: [выбранный вариант: за счет Продавца / за счет Покупателя].</p>
  <p>4.4. Способ доставки: ТК/курьер по согласованию Сторон, если Стороны не согласовали иной способ письменно.</p>
  <p>4.5. Продавец обеспечивает упаковку, достаточную для перевозки.</p>
  <p>4.6. Если выдача через ТК/ПВЗ: Покупатель обязан забрать Товар в срок хранения ТК. Дополнительные расходы хранения/возврата по вине Покупателя оплачивает Покупатель.</p>
  <h2>5. Передача, приемка, документы</h2>
  <p>5.1. Факт передачи подтверждается подписанием: накладной/акта приема-передачи/документа ТК. При доставке через ТК/курьера/ПВЗ фактической передачей считается вручение товара Покупателю (или его представителю), подтвержденное документом ТК/курьера/ПВЗ.</p>
  <p>5.2. Право собственности переходит к Покупателю с момента фактической передачи Товара (п. 5.1).</p>
  <p>5.3. Риск случайной гибели/повреждения переходит к Покупателю с момента фактической передачи Товара (п. 5.1).</p>
  <p>5.4. При получении Покупатель обязан: а) осмотреть упаковку и Товар; б) при видимых повреждениях/вскрытии/недостаче — сделать отметки в документах ТК/акте и зафиксировать фото/видео.</p>
  <p>5.5. Претензии по количеству/комплектности/видимым повреждениям предъявляются в течение 3 календарных дней с даты получения.</p>
  <p>5.6. Претензии по скрытым недостаткам — в пределах гарантийного срока (раздел 6).</p>
  <p>5.7. Вместе с Товаром Продавец передает документы (при наличии/применимости): гарантийный талон, инструкцию, документы ТК, документы об оплате.</p>
  <h2>6. Гарантия, сервис, возвраты</h2>
  <p>6.1. Гарантийный срок: 12 месяцев с даты передачи Товара, если больший срок не установлен производителем.</p>
  <p>6.2. Гарантия не распространяется на недостатки, возникшие вследствие нарушения эксплуатации, механических повреждений, попадания жидкости, несанкционированного ремонта, использования несовместимых аксессуаров, если это вызвало неисправность.</p>
  <p>6.3. Для обращения по гарантии Покупатель направляет Продавцу: описание проблемы, фото/видео, серийный номер, дату передачи, документы.</p>
  <p>6.4. Способ урегулирования: диагностика/ремонт/замена/возврат — по согласованию Сторон и применимым нормам закона.</p>
  <p>6.5. Доставка товара до Продавца/сервисного центра и обратно при гарантийном обращении оплачивается Покупателем, если иное не согласовано письменно.</p>
  <p>6.6. Срок диагностики и принятия решения по гарантийному обращению составляет 14 календарных дней с даты получения товара Продавцом/сервисным центром, если иной срок не установлен законом.</p>
  <p>6.7. Стороны подтверждают, что Покупатель приобретает товар [для личных нужд / для предпринимательской деятельности].</p>
  <p>6.8. Ограничение: условия Договора не могут ограничивать права Покупателя, если на отношения распространяются императивные нормы (например, о защите прав потребителей — при покупке для личных нужд).</p>
  <h2>7. Замена модели / отсутствие товара</h2>
  <p>7.1. Если конкретная модель/комплектация из Спецификации стала недоступна (снята с производства/отсутствует у поставщиков), Продавец обязан в течение 5 рабочих дней уведомить Покупателя и предложить: а) аналог/эквивалент не хуже по ключевым характеристикам без доплаты либо б) аналог с доплатой/скидкой по соглашению Сторон, либо в) возврат 100% оплаты в течение 10 рабочих дней с даты согласования возврата.</p>
  <p>7.2. Замена допускается только с письменного согласия Покупателя (сообщение в мессенджере/почте подходит).</p>
  <h2>8. Ответственность сторон</h2>
  <p>8.1. За нарушение срока передачи Товара Продавец по требованию Покупателя: либо передает Товар в дополнительный согласованный срок; либо возвращает оплаченные средства при отказе Покупателя от Договора.</p>
  <p>8.2. Стороны освобождаются от ответственности за нарушение обязательств при форс-мажоре (раздел 10).</p>
  <p>8.3. Сторона, нарушившая обязательства, возмещает другой стороне документально подтвержденные убытки в пределах, допускаемых законом.</p>
  <h2>9. Порядок уведомлений и переписка</h2>
  <p>9.1. Уведомления направляются по телефону/e-mail/мессенджеру, указанным в реквизитах.</p>
  <p>9.2. Сообщения и согласования в переписке (мессенджер/почта) признаются юридически значимыми, если позволяют идентифицировать стороны (номер/аккаунт).</p>
  <h2>10. Форс-мажор</h2>
  <p>10.1. Форс-мажор: чрезвычайные и непредотвратимые обстоятельства (запреты властей, ЧС, военные действия, сбои логистики из-за санкций/закрытий и т.п.).</p>
  <p>10.2. Сторона уведомляет другую сторону в течение 5 календарных дней.</p>
  <p>10.3. Если форс-мажор длится более 30 календарных дней, любая сторона вправе предложить расторжение с взаиморасчетами.</p>
  <h2>11. Споры и досудебное урегулирование</h2>
  <p>11.1. Все споры Стороны стремятся урегулировать путем переговоров.</p>
  <p>11.2. Стороны направляют претензию в письменной форме; рекомендуемый срок ответа — 10 календарных дней.</p>
  <p>11.3. При недостижении согласия спор передается в суд по правилам подсудности, установленным законом.</p>
  <h2>12. Конфиденциальность и запрет распространения договора</h2>
  <p>12.1. Конфиденциальной информацией по Договору являются: условия Договора и приложений, цена, скидки, сроки, реквизиты, персональные данные, переписка, документы поставки/логистики, а также иная информация, явно помеченная как конфиденциальная.</p>
  <p>12.2. Стороны обязуются не раскрывать и не передавать третьим лицам конфиденциальную информацию и сам Договор (в т.ч. сканы/фото), без предварительного письменного согласия другой Стороны.</p>
  <p>12.3. Стороны дают согласие на обработку и передачу персональных данных в объеме, необходимом для исполнения договора (банк/платежный агент, ТК/курьер/ПВЗ, сервисный центр/производитель, уполномоченные органы — в случаях, предусмотренных законом).</p>
  <p>12.4. Исключения: по закону/запросу органов, для защиты прав в споре, представителям (юрист/бухгалтер/аудитор), банку, ТК/курьеру/ПВЗ, сервисному центру/производителю в необходимом объеме.</p>
  <p>12.5. Если раскрытие допускается и законом не запрещено уведомление — Сторона заранее уведомляет другую Сторону о факте и объеме раскрытия.</p>
  <p>12.6. За нарушение конфиденциальности виновная Сторона уплачивает другой Стороне штраф [например: 30 000 руб.] и возмещает убытки сверх штрафа при наличии доказательств.</p>
  <p>12.7. Обязательства по конфиденциальности действуют 3 года после исполнения/расторжения Договора.</p>
  <p><strong>Важно:</strong> даже самая жёсткая конфиденциальность не может запрещать исполнение требований госорганов, если они законны.</p>
  <h2>13. Заключительные положения</h2>
  <p>13.1. Договор вступает в силу с момента подписания и действует до полного исполнения обязательств.</p>
  <p>13.2. Любые изменения — только в письменной форме, включая обмен подписанными сканами/фото.</p>
  <p>13.3. Недействительность одного условия не влияет на действительность остальных.</p>
  <p>13.4. Договор составлен в 2 экземплярах, по одному для каждой Стороны.</p>
  <h2>14. Реквизиты и подписи</h2>
  <table class="doc-table">
    <thead>
      <tr>
        <th style="width: 50%">Продавец (ИП)</th>
        <th style="width: 50%">Покупатель</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>
          ИП: {{supplier_name}}<br />
          ОГРНИП: {{supplier_ogrnip}}<br />
          ИНН: {{supplier_inn}}<br />
          Адрес: {{supplier_address}}<br />
          р/с: {{supplier_checking_account}}<br />
          Банк: {{supplier_bank_name}}<br />
          БИК: {{supplier_bik}}<br />
          к/с: {{supplier_correspondent_account}}<br />
          Тел.: {{supplier_phone}}<br />
          e-mail: {{supplier_email}}<br /><br />
          Подпись: _____________ / {{supplier_name}} /
        </td>
        <td>
          ФИО: {{buyer_name}}<br />
          Паспорт: [____]<br />
          Адрес: {{buyer_address}}<br />
          Тел.: [____]<br />
          e-mail: {{buyer_email}}<br /><br />
          Подпись: _____________ / {{buyer_name}} /
        </td>
      </tr>
    </tbody>
  </table>
  <h2>Приложение №1 — Спецификация</h2>
  <p>Примечание: в описании позиции рекомендуется указывать идентифицирующие признаки товара (модель, артикул, серийный номер, цвет/комплектация — при наличии).</p>
  <table class="doc-table">
    <thead>
      <tr>
        <th>№</th>
        <th>Наименование</th>
        <th>Кол-во</th>
        <th>Ед.</th>
        <th>Цена за ед., руб.</th>
        <th>Сумма, руб.</th>
      </tr>
    </thead>
    <tbody>
      {{#each items}}
        <tr>
          <td>{{index}}</td>
          <td>{{name}}</td>
          <td>{{qty}}</td>
          <td>{{unit}}</td>
          <td>{{price}}</td>
          <td>{{line_total}}</td>
        </tr>
      {{/each}}
    </tbody>
  </table>
  <p><strong>Итого:</strong> {{total_amount_formatted}}</p>
  <table style="width: 100%; border-collapse: collapse; margin-top: 12pt;">
    <tbody>
      <tr>
        <td style="width: 50%; border: none; padding: 0 8pt 0 0; vertical-align: top;">Продавец _____________ / {{supplier_name}} /</td>
        <td style="width: 50%; border: none; padding: 0 0 0 8pt; vertical-align: top;">Покупатель _____________ / {{buyer_name}} /</td>
      </tr>
    </tbody>
  </table>
</div>`;
const MOCK_TEMPLATE_CSS = '.document-page { font-family: "Times New Roman", serif; }';
const MOCK_TEMPLATE_VARIABLES = [
  { key: 'contract_type', description: 'Тип договора', sourceTable: 'contracts' },
  { key: 'contract_number', description: 'Номер договора', sourceTable: 'contracts' },
  { key: 'vat_rate', description: 'Ставка НДС', sourceTable: 'contracts' },
  { key: 'vat_mode', description: 'Режим НДС', sourceTable: 'contracts' },
];

export const MOCK_TEMPLATES: Template[] = [
  {
    id: 't1',
    name: 'Договор поставки с НДС',
    type: ContractType.SUPPLY,
    version: '2.2',
    updatedAt: '18.02.2026',
    isActive: true,
    content: MOCK_SUPPLY_WITH_VAT_TEMPLATE_CONTENT,
    css: MOCK_TEMPLATE_CSS,
    variables: MOCK_TEMPLATE_VARIABLES,
  },
  {
    id: 't2',
    name: 'Договор об уровне сервиса (SLA)',
    type: ContractType.SERVICE,
    version: '1.5',
    updatedAt: '15.10.2023',
    isActive: true,
    content: MOCK_TEMPLATE_CONTENT,
    css: MOCK_TEMPLATE_CSS,
    variables: MOCK_TEMPLATE_VARIABLES,
  },
  {
    id: 't3',
    name: 'Соглашение о конфиденциальности (NDA)',
    type: ContractType.NDA,
    version: '3.0',
    updatedAt: '01.09.2023',
    isActive: true,
    content: MOCK_TEMPLATE_CONTENT,
    css: MOCK_TEMPLATE_CSS,
    variables: MOCK_TEMPLATE_VARIABLES,
  },
  {
    id: 't4',
    name: 'Договор аренды оборудования',
    type: ContractType.RENTAL,
    version: '1.0',
    updatedAt: '12.08.2023',
    isActive: true,
    content: MOCK_TEMPLATE_CONTENT,
    css: MOCK_TEMPLATE_CSS,
    variables: MOCK_TEMPLATE_VARIABLES,
  },
  {
    id: 't5',
    name: 'Договор купли-продажи товара (расширенный, конфиденциальность)',
    type: ContractType.SUPPLY,
    version: '1.3',
    updatedAt: '25.02.2026',
    isActive: true,
    content: MOCK_GOODS_SALE_EXTENDED_CONFIDENTIALITY_TEMPLATE_CONTENT,
    css: MOCK_TEMPLATE_CSS,
    variables: MOCK_TEMPLATE_VARIABLES,
  },
];

export const MOCK_CONTRACTS: Contract[] = [
  { id: 'c1', number: 'Д-2023-085', title: 'Разработка сайта для ООО "ТехноСолюшнс"', type: ContractType.SERVICE, counterparty: MOCK_COUNTERPARTIES[0], status: ContractStatus.DRAFT, createdAt: '26.10.2023', amount: 500000 },
  { id: 'c2', number: 'Д-2023-084', title: 'Поставка логистического ПО', type: ContractType.SUPPLY, counterparty: MOCK_COUNTERPARTIES[1], status: ContractStatus.SIGNED, createdAt: '20.10.2023', amount: 1500000 },
  { id: 'c3', number: 'Д-2023-083', title: 'NDA с ИП Петров', type: ContractType.NDA, counterparty: MOCK_COUNTERPARTIES[2], status: ContractStatus.PENDING_APPROVAL, createdAt: '18.10.2023' },
];
