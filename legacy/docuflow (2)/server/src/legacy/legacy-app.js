const express = require('express');
const cors = require('cors');
const fsSync = require('fs');
const fs = require('fs/promises');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const puppeteer = require('puppeteer');
const HTMLtoDOCX = require('html-to-docx');
const JSZip = require('jszip');

const app = express();
const PORT = Number(process.env.PORT) || 3001;
const DATA_FILE = path.join(__dirname, '../../data.json');
const DB_FILE = path.join(__dirname, '../../data.sqlite');
const JSON_LIMIT = '10mb';
const SEED_MARKER_KEY = 'initial_seed_complete';
const V1_SUNSET_DATE = 'Mon, 30 Jun 2026 00:00:00 GMT';

app.use('/api', (req, res, next) => {
  if (!req.path.startsWith('/v2/')) {
    res.setHeader('Deprecation', 'true');
    res.setHeader('Sunset', V1_SUNSET_DATE);
  }
  next();
});

const CONTRACT_STATUS = {
  DRAFT: 'Черновик',
  PENDING_APPROVAL: 'На согласовании',
  SIGNED: 'Подписан',
};

const CONTRACT_TYPE = {
  SUPPLY: 'Договор поставки',
  SERVICE: 'Договор оказания услуг',
  NDA: 'Соглашение о конфиденциальности (NDA)',
  RENTAL: 'Договор аренды',
};

const DEFAULT_CONTRACT_PRICING = {
  vatRate: 'none',
  vatMode: 'included',
  markupPercent: 6,
  markupMode: 'per_item',
  markupCalcMode: 'simple',
};

const VALID_VAT_RATES = new Set(['none', '0', '10', '20']);
const VALID_VAT_MODES = new Set(['included', 'on_top']);
const VALID_MARKUP_MODES = new Set(['per_item', 'separate_line', 'proportional_total']);
const VALID_MARKUP_CALC_MODES = new Set(['simple', 'gross_up']);
const VALID_INVOICE_STATUSES = new Set(['Оплачен', 'Не оплачен']);
const VALID_COUNTERPARTY_TYPES = new Set(['ooo', 'ao', 'ip', 'person']);
const SUPPLY_LEGAL_ENTITY_TYPES = new Set(['ooo', 'ao', 'ip']);
const SUPPLY_LEGAL_ENTITIES_TEMPLATE_ID = 'tpl-supply-legal-entities-2026';
const SUPPLY_LEGAL_ENTITIES_TEMPLATE_NAME = 'Договор поставки (юрлица и ИП, расширенный)';
const VALID_CONTRACT_STATUSES = new Set([
  CONTRACT_STATUS.DRAFT,
  CONTRACT_STATUS.PENDING_APPROVAL,
  CONTRACT_STATUS.SIGNED,
  'Истек',
]);

const DEFAULT_TEMPLATE_CSS = `
  .preview-root {
    --font-main: "Times New Roman", "Liberation Serif", serif;
    --font-size-text: 11pt;
    --line-height: 1.3;
    --page-margin-top: 0mm;
    --page-margin-right: 15mm;
    --page-margin-bottom: 0mm;
    --page-margin-left: 15mm;
  }

  .document-page {
    width: 210mm;
    min-height: 297mm;
    box-sizing: border-box;
    padding: var(--page-margin-top) var(--page-margin-right) var(--page-margin-bottom) var(--page-margin-left);
    margin: 0 auto;
    color: #000;
    background: #fff;
    font-family: var(--font-main);
  }

  .document-page p {
    margin: 0 0 8pt;
    font-size: var(--font-size-text);
    line-height: var(--line-height);
    text-align: justify;
  }

  .document-page h1 {
    margin: 0 0 16pt;
    text-align: center;
    font-size: 14pt;
    font-weight: 700;
    text-transform: uppercase;
  }

  .document-page h2 {
    margin: 14pt 0 8pt;
    text-align: center;
    font-size: 12pt;
    font-weight: 700;
    text-transform: uppercase;
  }

  .doc-meta {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 12pt;
    font-size: 11pt;
  }

  .doc-table {
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0;
    font-size: 10pt;
  }

  .doc-table th,
  .doc-table td {
    border: 1px solid #000;
    padding: 4pt;
    text-align: left;
    vertical-align: top;
  }

  .doc-table th {
    font-weight: 700;
    background: #f3f4f6;
  }

  .align-right {
    text-align: right;
  }

  .summary {
    margin-top: 10pt;
    font-weight: 700;
  }

  /* Reduce unexpected splits inside key blocks. */
  .document-page h2,
  .document-page .doc-table,
  .document-page .summary {
    break-inside: avoid;
    page-break-inside: avoid;
  }

  .appendix-page-break {
    break-before: page;
    page-break-before: always;
    margin-top: 0;
    padding-top: 0;
  }

`;

const DEFAULT_TEMPLATE_VARIABLES = [
  { key: 'contract_number', description: 'Номер договора', sourceTable: 'contracts' },
  { key: 'contract_type', description: 'Тип договора', sourceTable: 'contracts' },
  { key: 'created_date', description: 'Дата создания договора', sourceTable: 'contracts' },
  { key: 'created_date_long', description: 'Дата договора (длинный формат)', sourceTable: 'contracts' },
  { key: 'city', description: 'Город подписания', sourceTable: 'settings' },
  { key: 'contract_signing_city', description: 'Город подписания (явно выбранный в мастере)', sourceTable: 'contracts' },
  { key: 'supplier_name', description: 'Название поставщика', sourceTable: 'settings' },
  { key: 'supplier_director_genitive', description: 'Директор поставщика (род. падеж)', sourceTable: 'settings' },
  { key: 'supplier_registration_label', description: 'ОГРН/ОГРНИП подпись поставщика', sourceTable: 'settings' },
  { key: 'supplier_registration_number', description: 'ОГРН/ОГРНИП поставщика', sourceTable: 'settings' },
  { key: 'supplier_inn', description: 'ИНН поставщика', sourceTable: 'settings' },
  { key: 'supplier_phone', description: 'Телефон поставщика', sourceTable: 'settings' },
  { key: 'supplier_email', description: 'Email поставщика', sourceTable: 'settings' },
  { key: 'supplier_address', description: 'Адрес поставщика', sourceTable: 'settings' },
  { key: 'supplier_bank_name', description: 'Банк поставщика', sourceTable: 'settings' },
  { key: 'supplier_bik', description: 'БИК поставщика', sourceTable: 'settings' },
  { key: 'supplier_checking_account', description: 'Расчетный счет поставщика', sourceTable: 'settings' },
  { key: 'supplier_correspondent_account', description: 'Корреспондентский счет поставщика', sourceTable: 'settings' },
  { key: 'supplier_signer_position', description: 'Должность подписанта поставщика', sourceTable: 'contracts' },
  { key: 'supplier_signer_name', description: 'ФИО подписанта поставщика', sourceTable: 'contracts' },
  { key: 'supplier_signer_basis', description: 'Основание полномочий подписанта поставщика', sourceTable: 'contracts' },
  { key: 'buyer_name', description: 'Название контрагента', sourceTable: 'counterparties' },
  { key: 'buyer_inn', description: 'ИНН контрагента', sourceTable: 'counterparties' },
  { key: 'buyer_has_kpp', description: 'Есть ли КПП у покупателя', sourceTable: 'counterparties' },
  { key: 'buyer_registration_label', description: 'ОГРН/ОГРНИП подпись', sourceTable: 'counterparties' },
  { key: 'buyer_registration_number', description: 'ОГРН/ОГРНИП контрагента', sourceTable: 'counterparties' },
  { key: 'buyer_signer_position', description: 'Должность подписанта покупателя', sourceTable: 'contracts' },
  { key: 'buyer_signer_name', description: 'ФИО подписанта покупателя', sourceTable: 'contracts' },
  { key: 'buyer_signer_basis', description: 'Основание полномочий подписанта покупателя', sourceTable: 'contracts' },
  { key: 'buyer_phone', description: 'Телефон контрагента', sourceTable: 'counterparties' },
  { key: 'buyer_email', description: 'Email контрагента', sourceTable: 'counterparties' },
  { key: 'buyer_address', description: 'Адрес контрагента', sourceTable: 'counterparties' },
  { key: 'total_amount_formatted', description: 'Итого к оплате', sourceTable: 'contracts' },
  { key: 'total_amount_words', description: 'Сумма прописью', sourceTable: 'contracts' },
  { key: 'total_amount_words_full', description: 'Сумма прописью (рубли и копейки)', sourceTable: 'contracts' },
  { key: 'payment_terms', description: 'Срок оплаты, дни', sourceTable: 'contracts' },
  { key: 'prepayment_percent', description: 'Размер предоплаты, %', sourceTable: 'contracts' },
  { key: 'prepayment_amount_formatted', description: 'Сумма предоплаты', sourceTable: 'contracts' },
  { key: 'final_payment_percent', description: 'Процент окончательного расчета', sourceTable: 'contracts' },
  { key: 'final_payment_amount_formatted', description: 'Сумма окончательного расчета', sourceTable: 'contracts' },
  { key: 'payment_due_date_display', description: 'Срок окончательного расчета (дата)', sourceTable: 'contracts' },
  { key: 'payment_option_100_mark', description: 'Отметка варианта оплаты 100% предоплата', sourceTable: 'contracts' },
  { key: 'payment_option_partial_mark', description: 'Отметка варианта оплаты частичная предоплата', sourceTable: 'contracts' },
  { key: 'payment_option_custom_mark', description: 'Отметка варианта оплаты иное', sourceTable: 'contracts' },
  { key: 'custom_payment_terms_display', description: 'Текст иного условия оплаты', sourceTable: 'contracts' },
  { key: 'selected_payment_terms_clause', description: 'Выбранный вариант оплаты для раздела 3.3', sourceTable: 'contracts' },
  { key: 'selected_payment_terms_spec_clause', description: 'Выбранный вариант оплаты для Спецификации', sourceTable: 'contracts' },
  { key: 'vat_rate', description: 'Ставка НДС', sourceTable: 'contracts' },
  { key: 'vat_mode', description: 'Режим НДС (включен/сверху)', sourceTable: 'contracts' },
  { key: 'goods_sale_vat_clause_text', description: 'Готовая формулировка пункта НДС для шаблона купли-продажи', sourceTable: 'contracts' },
  { key: 'delivery_city_display', description: 'Город доставки (с fallback)', sourceTable: 'contracts' },
  { key: 'delivery_term_days', description: 'Срок поставки в днях', sourceTable: 'contracts' },
  { key: 'delivery_term_basis', description: 'Основание отсчета срока поставки', sourceTable: 'contracts' },
  { key: 'delivery_cost_payer_label', description: 'Кто оплачивает доставку (текст для шаблона)', sourceTable: 'contracts' },
  { key: 'delivery_cost_payer_supplier_label', description: 'Кто оплачивает доставку (Поставщик/Покупатель)', sourceTable: 'contracts' },
  { key: 'delivery_method_label', description: 'Способ доставки (текст для шаблона)', sourceTable: 'contracts' },
  { key: 'confidentiality_penalty_amount_formatted', description: 'Штраф за конфиденциальность (форматированный)', sourceTable: 'contracts' },
  { key: 'seller_ip_name', description: 'ФИО ИП продавца (без префикса ИП)', sourceTable: 'settings' },
  { key: 'seller_ip_full_intro', description: 'Вступительная форма продавца-ИП', sourceTable: 'settings' },
  { key: 'seller_ip_inn_display', description: 'ИНН продавца-ИП (с placeholder)', sourceTable: 'settings' },
  { key: 'seller_ip_ogrnip_display', description: 'ОГРНИП продавца-ИП (с placeholder)', sourceTable: 'settings' },
  { key: 'supplier_is_ip', description: 'Поставщик является ИП (boolean)', sourceTable: 'settings' },
  { key: 'supplier_is_person', description: 'Поставщик является физлицом (boolean)', sourceTable: 'settings' },
  { key: 'buyer_person_full_name_display', description: 'ФИО покупателя-физлица', sourceTable: 'contracts' },
  { key: 'buyer_person_passport_display', description: 'Паспорт покупателя-физлица', sourceTable: 'contracts' },
  { key: 'buyer_person_passport_issued_display', description: 'Кем/когда выдан паспорт покупателя', sourceTable: 'contracts' },
  { key: 'buyer_person_address_display', description: 'Адрес покупателя-физлица', sourceTable: 'contracts' },
  { key: 'buyer_person_phone_display', description: 'Телефон покупателя-физлица', sourceTable: 'contracts' },
  { key: 'buyer_person_email_display', description: 'Email покупателя-физлица', sourceTable: 'contracts' },
  { key: 'seller_person_full_name_display', description: 'ФИО продавца-физлица', sourceTable: 'settings' },
  { key: 'seller_person_passport_display', description: 'Паспорт продавца-физлица', sourceTable: 'settings' },
  { key: 'seller_person_passport_issued_display', description: 'Кем/когда выдан паспорт продавца', sourceTable: 'settings' },
  { key: 'seller_person_address_display', description: 'Адрес продавца-физлица', sourceTable: 'settings' },
  { key: 'seller_person_phone_display', description: 'Телефон продавца-физлица', sourceTable: 'settings' },
  { key: 'seller_person_email_display', description: 'Email продавца-физлица', sourceTable: 'settings' },
  { key: 'items', description: 'Позиции спецификации для #each', sourceTable: 'invoices' },
];

const DEFAULT_TEMPLATE_CONTENT = `
  <div class="document-page contract-snapshot">
    <h1>{{contract_type}} № {{contract_number}}</h1>

    <div class="doc-meta">
      <span>г. {{city}}</span>
      <span>{{created_date}}</span>
    </div>

    <p>
      <strong>{{supplier_name}}</strong>, именуемое в дальнейшем «Поставщик», в лице
      {{supplier_director_genitive}}, с одной стороны, и
      <strong>{{buyer_name}}</strong>, именуемое в дальнейшем «Покупатель», с другой стороны,
      заключили настоящий договор о нижеследующем.
    </p>

    <h2>1. Предмет договора</h2>
    <p>
      Поставщик обязуется передать Покупателю товар (работы, услуги) в соответствии со спецификацией,
      а Покупатель обязуется принять и оплатить его на сумму <strong>{{total_amount_formatted}}</strong>.
    </p>
    {{#if has_prepayment}}
      <p>
        Покупатель вносит предоплату в размере {{prepayment_percent}}% в течение {{payment_terms}} календарных дней.
      </p>
    {{/if}}
    {{#if has_delivery}}
      <p>Поставка (сдача работ) осуществляется не позднее {{delivery_date}}.</p>
    {{/if}}

    <h2>2. Спецификация</h2>
    <table class="doc-table">
      <thead>
        <tr>
          <th style="width: 8%">№</th>
          <th style="width: 42%">Наименование</th>
          <th style="width: 10%">Кол-во</th>
          <th style="width: 10%">Ед.</th>
          <th style="width: 15%">Цена</th>
          <th style="width: 15%">Сумма</th>
        </tr>
      </thead>
      <tbody>
        {{#each items}}
          <tr>
            <td>{{index}}</td>
            <td>{{name}}</td>
            <td>{{qty}}</td>
            <td>{{unit}}</td>
            <td class="align-right">{{price}}</td>
            <td class="align-right">{{line_total}}</td>
          </tr>
        {{/each}}
      </tbody>
    </table>

    <p class="summary">Итого к оплате: {{total_amount_formatted}}</p>

    <h2>3. Реквизиты сторон</h2>
    <p>
      Поставщик: {{supplier_name}}, ИНН {{supplier_inn}}
      {{#if supplier_has_kpp}}, КПП {{supplier_kpp}}{{/if}},
      {{supplier_registration_label}} {{supplier_registration_number}}.
    </p>
    <p>
      Покупатель: {{buyer_name}}, ИНН {{buyer_inn}}, {{buyer_registration_label}} {{buyer_registration_number}}.
    </p>
  </div>
`;

const SUPPLY_WITH_VAT_TEMPLATE_CONTENT = `
  <div class="document-page contract-snapshot">
    <h1>ДОГОВОР ПОСТАВКИ № {{contract_number}}</h1>

    <div class="doc-meta">
      <span>г. {{city}}</span>
      <span>{{created_date_long}}</span>
    </div>

    <p>
      <strong>{{supplier_name}}</strong>, именуемое в дальнейшем «Поставщик», в лице
      {{supplier_director_genitive}}, действующего на основании устава, с одной стороны, и
      <strong>{{buyer_name}}</strong>, именуемое в дальнейшем «Покупатель», с другой стороны,
      совместно именуемые «Стороны», заключили настоящий договор о нижеследующем.
    </p>

    <h2>1. Предмет договора</h2>
    <p>
      Поставщик обязуется передать в собственность Покупателя товар согласно спецификации,
      а Покупатель обязуется принять и оплатить такой товар на условиях настоящего договора.
    </p>

    <h2>2. Цена договора и НДС</h2>
    <p>
      Общая стоимость товара по настоящему договору составляет <strong>{{total_amount_formatted}}</strong>.
      Цена сформирована с учетом НДС по ставке <strong>{{vat_rate}}%</strong>
      (режим учета НДС: <strong>{{vat_mode}}</strong>).
    </p>

    <h2>3. Порядок расчетов</h2>
    {{#if has_prepayment}}
      <p>
        Покупатель перечисляет предоплату в размере {{prepayment_percent}}% в течение
        {{payment_terms}} календарных дней с даты выставления счета.
      </p>
    {{/if}}
    <p>
      Окончательный расчет производится безналичным перечислением денежных средств
      на расчетный счет Поставщика.
    </p>

    <h2>4. Спецификация</h2>
    {{#if has_items}}
      <table class="doc-table">
        <thead>
          <tr>
            <th style="width: 8%">№</th>
            <th style="width: 42%">Наименование</th>
            <th style="width: 10%">Кол-во</th>
            <th style="width: 10%">Ед.</th>
            <th style="width: 15%">Цена</th>
            <th style="width: 15%">Сумма</th>
          </tr>
        </thead>
        <tbody>
          {{#each items}}
            <tr>
              <td>{{index}}</td>
              <td>{{name}}</td>
              <td>{{qty}}</td>
              <td>{{unit}}</td>
              <td class="align-right">{{price}}</td>
              <td class="align-right">{{line_total}}</td>
            </tr>
          {{/each}}
        </tbody>
      </table>
    {{/if}}
    <p class="summary">Итого к оплате: {{total_amount_formatted}}</p>

    <h2>5. Сроки и порядок поставки</h2>
    {{#if has_delivery}}
      <p>Срок поставки товара: не позднее {{delivery_date}}.</p>
    {{/if}}
    <p>
      Моментом исполнения обязательства Поставщика по поставке считается дата подписания
      товаросопроводительных документов обеими Сторонами.
    </p>

    <h2>6. Ответственность сторон</h2>
    {{#if has_penalty}}
      <p>
        За нарушение сроков оплаты Покупатель уплачивает Поставщику пеню
        в размере {{penalty_percent_per_day}}% от просроченной суммы за каждый день просрочки.
      </p>
    {{/if}}
    <p>
      Во всем ином, что не урегулировано настоящим договором, Стороны руководствуются
      действующим законодательством Российской Федерации.
    </p>

    <h2>7. Реквизиты сторон</h2>
    <p>
      Поставщик: {{supplier_name}}, ИНН {{supplier_inn}}
      {{#if supplier_has_kpp}}, КПП {{supplier_kpp}}{{/if}},
      {{supplier_registration_label}} {{supplier_registration_number}}.
    </p>
    <p>
      Покупатель: {{buyer_name}}, ИНН {{buyer_inn}}, {{buyer_registration_label}} {{buyer_registration_number}}.
    </p>
  </div>
`;

const SUPPLY_LEGAL_ENTITIES_TEMPLATE_CONTENT = `
  <div class="document-page contract-snapshot">
    <h1>ДОГОВОР ПОСТАВКИ № {{contract_number}}</h1>

    <div class="doc-meta">
      <span>г. {{contract_signing_city}}</span>
      <span>{{created_date_long}}</span>
    </div>

    <p>
      {{#if supplier_is_ip}}
        Индивидуальный предприниматель {{seller_ip_name}}, ИНН {{supplier_inn}}, ОГРНИП {{supplier_registration_number}},
        именуемый в дальнейшем «Поставщик», с одной стороны,
      {{/if}}
      {{#if supplier_is_company}}
        {{supplier_name}}, ОГРН {{supplier_registration_number}}, ИНН {{supplier_inn}}, КПП {{supplier_kpp}},
        в лице {{supplier_signer_position}} {{supplier_signer_name}}, действующего на основании {{supplier_signer_basis}},
        именуемое в дальнейшем «Поставщик», с одной стороны,
      {{/if}}
      и
      {{#if buyer_is_ip}}
        Индивидуальный предприниматель {{buyer_name}}, ОГРНИП {{buyer_registration_number}}, ИНН {{buyer_inn}},
        в лице {{buyer_signer_position}} {{buyer_signer_name}}, действующего на основании {{buyer_signer_basis}},
        именуемый в дальнейшем «Покупатель», с другой стороны,
      {{/if}}
      {{#if buyer_is_company}}
        {{buyer_name}}, ОГРН {{buyer_registration_number}}, ИНН {{buyer_inn}}, КПП {{buyer_kpp}},
        в лице {{buyer_signer_position}} {{buyer_signer_name}}, действующего на основании {{buyer_signer_basis}},
        именуемое в дальнейшем «Покупатель», с другой стороны,
      {{/if}}
      совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем.
    </p>

    <h2>1. ТЕРМИНЫ И ОПРЕДЕЛЕНИЯ</h2>
    <p>1.1. «Товар» — товары, указанные в Спецификации (Приложение № 1) к Договору.</p>
    <p>1.2. «Спецификация» — документ, содержащий ассортимент, количество, цену, общую стоимость Товара и иные параметры партии Товара; является неотъемлемой частью Договора.</p>
    <p>1.3. «Рабочий день» — день, который не является выходным или нерабочим праздничным днем в Российской Федерации.</p>
    <p>1.4. «Передаточные документы» — УПД / ТОРГ-12 / товарная накладная / экспедиторская расписка/накладная транспортной компании и иные документы, подтверждающие передачу Товара.</p>
    <p>1.5. «Недостаток (дефект)» — несоответствие Товара обязательным требованиям, условиям Спецификации или обычным требованиям к такому товару.</p>

    <h2>2. ПРЕДМЕТ ДОГОВОРА</h2>
    <p>2.1. Поставщик обязуется поставить, а Покупатель — принять и оплатить Товар в ассортименте, количестве и по цене, определенным Спецификацией (Приложение № 1).</p>
    <p>2.2. Поставка осуществляется партиями в порядке, предусмотренном настоящим Договором. Если иное не согласовано Сторонами письменно, поставка осуществляется одной партией.</p>
    <p>2.3. Товар приобретается Покупателем для использования в предпринимательской деятельности (и/или дальнейшей реализации).</p>

    <h2>3. ЦЕНА ДОГОВОРА И ПОРЯДОК РАСЧЕТОВ</h2>
    <p>3.1. Общая стоимость Товара по Договору составляет {{total_amount_formatted}}, согласно Спецификации.</p>
    <p>3.2. {{goods_sale_vat_clause_text}}</p>
    <p>3.3. Условие оплаты: {{selected_payment_terms_clause}}</p>
    <p>Срок(и) оплаты указываются в счете/Спецификации; если срок не указан — оплата производится в течение 5 (пяти) рабочих дней с даты подписания Договора.</p>
    <p>3.4. Обязательство Покупателя по оплате считается исполненным с момента зачисления денежных средств на расчетный счет Поставщика.</p>
    <p>3.5. Банковские комиссии и расходы по перечислению денежных средств несет плательщик, если иное не согласовано Сторонами.</p>
    <p>3.6. При неоплате Товара в срок, указанный в счете/Спецификации, Поставщик вправе приостановить отгрузку/поставку до момента поступления оплаты. При просрочке оплаты более 5 (пяти) рабочих дней Поставщик вправе отказаться от исполнения Договора в одностороннем порядке, уведомив Покупателя по электронной почте. Такое уведомление считается полученным по правилам п. 10.1 при направлении на адреса, указанные в п. 11.1.</p>
    <p>3.7. Стороны признают, что согласование существенных условий поставки (ассортимент, количество, цена, срок, ТК, адрес получателя) может осуществляться в Спецификации, счете, а также в переписке с адресов электронной почты, указанных в п. 11.1. Такие сообщения считаются совершенными в простой письменной форме.</p>
    <p>3.8. Отмена заказа и возврат предоплаты: для Товара в наличии отмена до отгрузки допускается с возвратом предоплаты за вычетом фактически понесенных и документально подтвержденных расходов Поставщика; возврат остатка предоплаты производится в течение 7 (семи) рабочих дней после подтверждения размера таких расходов. Для Товара «под заказ» после размещения заказа/закупки у поставщика Поставщика предоплата невозвратна в части фактически понесенных и документально подтвержденных расходов.</p>

    <h2>4. СРОКИ И УСЛОВИЯ ПОСТАВКИ. ПЕРЕХОД ПРАВА СОБСТВЕННОСТИ И РИСКОВ</h2>
    <p>4.1. Срок поставки: а) Товар, имеющийся в наличии у Поставщика, поставляется в течение 5 (пяти) рабочих дней с даты поступления оплаты; б) Товар «под заказ» поставляется в течение {{delivery_term_days}} календарных дней {{delivery_term_basis}}, если иной срок не согласован Сторонами письменно (в том числе в счете/переписке).</p>
    <p>4.2. Поставка осуществляется путем отгрузки через транспортную компанию (ТК). ТК выбирается Поставщиком по согласованию с Покупателем. Услуги ТК оплачивает Покупатель. По просьбе Покупателя Поставщик вправе организовать оплату доставки с последующим возмещением Покупателем на основании подтверждающих документов/счета. Конкретная ТК и получатель указываются в транспортных документах.</p>
    <p>4.3. При поставке через ТК риск случайной гибели/повреждения Товара переходит к Покупателю в момент вручения Товара Покупателю (получателю), подтвержденного документами ТК/курьера. До момента вручения Товара риск несет Поставщик. Если доставка осуществляется до терминала ТК/ПВЗ и получение зависит от Покупателя, риск переходит к Покупателю с даты уведомления ТК о готовности к выдаче (или с даты прибытия груза в терминал), если неполучение обусловлено причинами, зависящими от Покупателя. Страхование груза оформляется по письменному запросу Покупателя и оплачивается Покупателем, если Стороны письменно не согласовали иное.</p>
    <p>4.4. Право собственности на Товар переходит к Покупателю при условии полной оплаты Товара — в момент вручения Товара Покупателю (получателю) и подписания Передаточных документов. До полной оплаты право собственности сохраняется за Поставщиком.</p>
    <p>4.5. Если Покупатель не обеспечивает приемку Товара в согласованную дату/время (отказ от приемки без законных оснований, отсутствие представителей, невозможность разгрузки), Поставщик вправе: (а) перенести дату поставки, (б) передать Товар на ответственное хранение за счет Покупателя, (в) вернуть Товар Поставщику. Все дополнительные расходы возмещаются Покупателем по факту и при документальном подтверждении.</p>
    <p>4.6. Поставщик вправе осуществлять частичную поставку (поставка партиями) только при письменном согласовании с Покупателем.</p>
    <p>4.7. Упаковка и маркировка: Товар поставляется в заводской упаковке. При необходимости дополнительной транспортной упаковки (обрешетка, дополнительная защита) условия и стоимость согласуются отдельно.</p>

    <h2>5. ПРИЕМКА ТОВАРА</h2>
    <p>5.1. Приемка Товара по количеству, комплектности, целостности упаковки и наличию видимых повреждений осуществляется Покупателем при получении Товара.</p>
    <p>5.2. При обнаружении недостачи, пересортицы, некомплектности или видимых повреждений Покупатель обязан немедленно зафиксировать это в Передаточных документах (в том числе документах ТК) и составить акт (при наличии возможности — с фото/видео фиксацией). В Спецификации/УПД фиксируются количество единиц Товара и комплектность; при приемке Покупатель вправе вскрыть упаковку и проверить Товар в присутствии представителя ТК/курьера (если это допускается правилами перевозчика). Претензии по некомплектности внутри упаковки заявляются не позднее 5 (пяти) рабочих дней с даты получения Товара.</p>
    <p>5.3. Претензии по скрытым недостаткам (не выявляемым при обычном осмотре при приемке) заявляются в письменной форме в течение 10 (десяти) рабочих дней с момента обнаружения, но в пределах гарантийного срока, с описанием дефекта и приложением фото/видео материалов.</p>
    <p>5.4. Стороны согласовали, что отсутствие письменных претензий в течение 2 (двух) рабочих дней после приемки по вопросам количества мест, целостности упаковки и видимых повреждений означает принятие Товара без замечаний по указанным вопросам. Претензии по некомплектности внутри упаковки рассматриваются в срок, установленный п. 5.2.</p>
    <p>5.5. Уполномоченные представители Сторон подтверждаются доверенностью/приказом/иным документом. Поставщик вправе отказать в передаче Товара лицу без подтверждения полномочий.</p>

    <h2>6. ГАРАНТИЯ. ПОРЯДОК УРЕГУЛИРОВАНИЯ ПРЕТЕНЗИЙ ПО КАЧЕСТВУ</h2>
    <p>6.1. Гарантийный срок на Товар составляет 12 (двенадцать) месяцев с даты передачи Товара Покупателю, если иное не указано производителем или в Спецификации.</p>
    <p>6.2. Гарантия распространяется на производственные дефекты при условии соблюдения Покупателем правил эксплуатации, хранения и транспортировки.</p>
    <p>6.3. Гарантия не распространяется на случаи: механические повреждения; попадание влаги/жидкостей; следы вскрытия, ремонта или модификаций третьими лицами; использование неоригинальных/неподходящих зарядных устройств; повреждения, вызванные нарушением инструкций производителя, перепадами напряжения, воздействием высоких температур, химических веществ и т. п.</p>
    <p>6.4. Для рассмотрения гарантийного случая Покупатель направляет претензию по электронной почте Поставщика (п. 11.1) и предоставляет: (а) наименование Товара и количество, (б) описание проявления дефекта, (в) фото/видео, (г) копии Передаточных документов.</p>
    <p>6.5. Поставщик вправе провести проверку качества/диагностику. На период диагностики Товар передается Поставщику или в согласованный сервисный центр. Доставка Товара на диагностику осуществляется за счет Покупателя. Если гарантийный случай подтвержден, Поставщик компенсирует документально подтвержденные расходы на доставку и/или организует обратную отправку за свой счет.</p>
    <p>6.6. Срок рассмотрения претензии и принятия решения — до 10 (десяти) рабочих дней с момента получения всех материалов и, при необходимости, Товара для диагностики.</p>
    <p>6.7. При подтверждении гарантийного случая Поставщик по своему выбору: (а) устраняет недостаток (ремонт), (б) заменяет Товар на аналогичный, (в) уменьшает цену, (г) возвращает уплаченные денежные средства за неисправный Товар. Конкретный способ урегулирования согласуется с учетом наличия Товара и сроков ремонта.</p>
    <p>6.8. Если дефект не подтвержден (например, выявлено нарушение условий эксплуатации), Поставщик уведомляет Покупателя; расходы на диагностику и доставку несет Покупатель.</p>
    <p>6.9. На замененный/отремонтированный Товар гарантийный срок исчисляется в соответствии с законодательством РФ и/или правилами производителя (при наличии).</p>
    <p>6.10. Поставщик не несет ответственности за работоспособность и доступность сторонних цифровых сервисов/платформ (магазинов приложений, онлайн-сервисов), обновлений, региональных ограничений, требований регистрации аккаунтов, а также за изменения политик производителей и правообладателей, которые не зависят от Поставщика.</p>
    <p>6.11. Возврат Товара надлежащего качества не допускается, за исключением случаев, прямо предусмотренных законодательством РФ.</p>
    <p>6.12. Для случаев первичного брака (DOA) электроники, выявленного в течение 7 (семи) календарных дней с даты получения Товара, применяется упрощенный порядок урегулирования (обмен/замена при подтверждении дефекта, сохранности заводской маркировки/пломб и предоставлении фото/видео материалов).</p>

    <h2>7. ОТВЕТСТВЕННОСТЬ СТОРОН</h2>
    <p>7.1. Стороны несут ответственность за неисполнение или ненадлежащее исполнение обязательств по Договору в соответствии с законодательством РФ и условиями Договора.</p>
    <p>7.2. Сторона, нарушившая обязательство, возмещает другой Стороне документально подтвержденные прямые убытки, причиненные таким нарушением, в пределах, установленных настоящим Договором.</p>
    <p>7.3. Стороны не несут ответственности за упущенную выгоду, косвенные или последующие убытки, если иное прямо не предусмотрено законом.</p>
    <p>7.4. Общая ответственность Поставщика по Договору ограничивается суммой, фактически уплаченной Покупателем по Договору.</p>

    <h2>8. ОБСТОЯТЕЛЬСТВА НЕПРЕОДОЛИМОЙ СИЛЫ</h2>
    <p>8.1. Стороны освобождаются от ответственности за полное или частичное неисполнение обязательств, если оно явилось следствием обстоятельств непреодолимой силы (форс-мажор), которые Стороны не могли предвидеть или предотвратить разумными мерами.</p>
    <p>8.2. Сторона, для которой наступили такие обстоятельства, уведомляет другую Сторону по электронной почте в течение 5 (пяти) рабочих дней с момента наступления, при возможности предоставляя подтверждающие документы (в т. ч. компетентных органов/ТПП).</p>
    <p>8.3. Если форс-мажор продолжается более 30 (тридцати) календарных дней, каждая из Сторон вправе инициировать расторжение Договора без применения мер ответственности, с проведением взаиморасчетов за фактически поставленный Товар.</p>

    <h2>9. КОНФИДЕНЦИАЛЬНОСТЬ И КОМПЛАЕНС</h2>
    <p>9.1. Стороны обязуются не раскрывать третьим лицам условия Договора, коммерческие условия и переписку по Договору, за исключением случаев, прямо предусмотренных законом или необходимых для исполнения Договора (банк, ТК, бухгалтерия, аудиторы).</p>
    <p>9.2. Стороны подтверждают, что действуют добросовестно, не допускают коррупционных действий и предоставляют достоверные сведения, необходимые для исполнения Договора.</p>

    <h2>10. РАЗРЕШЕНИЕ СПОРОВ</h2>
    <p>10.1. Претензионный порядок обязателен. Претензия направляется по электронной почте, указанной в п. 11.1, и считается полученной на следующий рабочий день после отправки при наличии подтверждения отправки/доставки. Достаточным подтверждением доставки/получения уведомления является отчет сервера отправителя, квитанция о доставке или иной технический лог.</p>
    <p>10.2. Срок рассмотрения претензии — 10 (десять) рабочих дней с даты получения.</p>
    <p>10.3. При недостижении соглашения спор подлежит рассмотрению в Арбитражном суде Свердловской области (по месту нахождения Поставщика), если иное не согласовано Сторонами и не противоречит императивным нормам.</p>

    <h2>11. ДОКУМЕНТООБОРОТ И УВЕДОМЛЕНИЯ</h2>
    <p>11.1. Стороны признают юридическую силу документов и уведомлений, направленных по электронной почте:</p>
    <p>11.1.1. Электронная почта Поставщика: {{supplier_email_display}}</p>
    <p>11.1.2. Электронная почта Покупателя: {{buyer_email_display}}</p>
    <p>11.2. Копии документов, подписанные и направленные в виде сканов/фото, имеют юридическую силу до обмена оригиналами. Оригиналы направляются по запросу другой Стороны в течение 7 (семи) рабочих дней почтовым отправлением.</p>
    <p>11.3. Изменение реквизитов и контактных данных Стороны обязуются сообщать друг другу в течение 3 (трех) рабочих дней; риск последствий несообщения несет нарушившая Сторона.</p>
    <p>11.4. Стороны подтверждают, что переписка с адресов электронной почты, указанных в п. 11.1, является юридически значимой и может использоваться для согласования условий поставки и подтверждения исполнения обязательств.</p>

    <h2>12. СРОК ДЕЙСТВИЯ ДОГОВОРА. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ</h2>
    <p>12.1. Договор вступает в силу с момента подписания Сторонами и действует до полного исполнения обязательств.</p>
    <p>12.2. Любые изменения и дополнения действительны при условии их письменного оформления и подписания Сторонами (в т. ч. путем обмена сканами), за исключением случаев согласования условий в порядке, прямо предусмотренном п. 3.7 и п. 11.4 Договора.</p>
    <p>12.3. Недействительность отдельного положения Договора не влечет недействительности Договора в целом.</p>
    <p>12.4. Приложение № 1 (Спецификация) является неотъемлемой частью Договора.</p>
    <p>12.5. Договор составлен в двух экземплярах, имеющих одинаковую юридическую силу, по одному для каждой Стороны.</p>

    <h2>РЕКВИЗИТЫ И ПОДПИСИ СТОРОН</h2>
    <table class="doc-table">
      <tbody>
        <tr>
          <td style="width: 50%">
            <strong>ПОСТАВЩИК:</strong><br /><br />
            {{supplier_name}}<br />
            ИНН {{supplier_inn}}<br />
            {{supplier_registration_label}} {{supplier_registration_number}}<br />
            Адрес: {{supplier_address_display}}<br /><br />
            Р/с: {{supplier_checking_account_display}}<br />
            Банк: {{supplier_bank_name_display}}<br />
            К/с: {{supplier_correspondent_account_display}}<br />
            БИК: {{supplier_bik_display}}<br /><br />
            _____________________ /{{supplier_signer_name}}/<br />
            М.П. (при наличии)
          </td>
          <td style="width: 50%">
            <strong>ПОКУПАТЕЛЬ:</strong><br /><br />
            {{buyer_name}}<br />
            ИНН {{buyer_inn}}{{#if buyer_has_kpp}} / КПП {{buyer_kpp}}{{/if}}<br />
            {{buyer_registration_label}} {{buyer_registration_number}}<br />
            Адрес: {{buyer_address}}<br /><br />
            Р/с: {{buyer_checking_account}}<br />
            Банк: {{buyer_bank_name}}<br />
            К/с: {{buyer_correspondent_account}}<br />
            БИК: {{buyer_bik}}<br /><br />
            _____________________ /{{buyer_signer_name}}/<br />
            М.П. (при наличии)
          </td>
        </tr>
      </tbody>
    </table>

    <h2 class="appendix-page-break">ПРИЛОЖЕНИЕ № 1</h2>
    <p>Спецификация к Договору поставки № {{contract_number}} от {{created_date_long}}.</p>
    <table class="doc-table">
      <thead>
        <tr>
          <th style="width: 8%">№</th>
          <th style="width: 42%">Наименование товара</th>
          <th style="width: 10%">Кол-во</th>
          <th style="width: 10%">Ед. изм.</th>
          <th style="width: 15%">Цена за единицу, руб.</th>
          <th style="width: 15%">Сумма, руб.</th>
        </tr>
      </thead>
      <tbody>
        {{#each items}}
          <tr>
            <td>{{index}}</td>
            <td>{{name}}</td>
            <td>{{qty}}</td>
            <td>{{unit}}</td>
            <td class="align-right">{{price}}</td>
            <td class="align-right">{{line_total}}</td>
          </tr>
        {{/each}}
      </tbody>
    </table>
    <p class="summary">Итого: {{total_amount_formatted}}. {{goods_sale_vat_clause_text}}.</p>
    <p>Условие оплаты: {{selected_payment_terms_spec_clause}}.</p>
    <p>Поставщик вправе осуществлять фото/видеофиксацию комплектации, упаковки и передачи Товара в ТК; такие материалы могут использоваться как доказательство надлежащей отгрузки.</p>
  </div>
`;

const GOODS_SALE_EXTENDED_CONFIDENTIALITY_TEMPLATE_CONTENT = `
  <div class="document-page contract-snapshot">
    <h1>
      ДОГОВОР КУПЛИ-ПРОДАЖИ ТОВАРА № {{contract_number}}
    </h1>

    <div class="doc-meta">
      <span>г. {{contract_signing_city}}</span>
      <span>{{created_date_long}}</span>
    </div>

    {{#if supplier_is_ip}}
      <p>
        {{seller_ip_full_intro}}, ОГРНИП {{seller_ip_ogrnip_display}}, ИНН {{seller_ip_inn_display}},
        адрес регистрации: {{supplier_address_display}}, тел.: {{supplier_phone_display}}, e-mail: {{supplier_email_display}},
        именуемый далее «Продавец», с одной стороны, и
        {{buyer_person_full_name_display}}{{buyer_person_passport_clause}}{{buyer_person_passport_issued_clause}}, адрес: {{buyer_person_address_display}},
        тел.: {{buyer_person_phone_display}}, e-mail: {{buyer_person_email_display}},
        именуемый далее «Покупатель», с другой стороны,
        совместно именуемые «Стороны», заключили настоящий договор (далее — «Договор») о нижеследующем.
      </p>
    {{/if}}
    {{#if supplier_is_person}}
      <p>
        Гражданин РФ {{seller_person_full_name_display}}{{seller_person_passport_clause}}{{seller_person_passport_issued_clause}}, адрес регистрации: {{seller_person_address_display}},
        тел.: {{seller_person_phone_display}}, e-mail: {{seller_person_email_display}},
        именуемый далее «Продавец», с одной стороны, и
        {{buyer_person_full_name_display}}{{buyer_person_passport_clause}}{{buyer_person_passport_issued_clause}}, адрес: {{buyer_person_address_display}},
        тел.: {{buyer_person_phone_display}}, e-mail: {{buyer_person_email_display}},
        именуемый далее «Покупатель», с другой стороны,
        совместно именуемые «Стороны», заключили настоящий договор (далее — «Договор») о нижеследующем.
      </p>
    {{/if}}

    <h2>1. Предмет договора</h2>
    <p>
      1.1. Продавец обязуется передать в собственность Покупателю товар, указанный в Приложении №1
      (Спецификация), а Покупатель обязуется принять Товар и оплатить его на условиях Договора.
    </p>
    <p>1.2. Спецификация (Приложение №1) является неотъемлемой частью Договора.</p>

    <h2>2. Цена, налоги, общая сумма</h2>
    <p>
      2.1. Общая стоимость Товара по Договору составляет:
      <strong>{{total_amount_formatted}}</strong> ({{total_amount_words_full}}).
    </p>
    <p>2.2. Цена фиксирована и не подлежит одностороннему изменению Продавцом.</p>
    <p>{{goods_sale_vat_clause_text}}</p>

    <h2>3. Порядок расчетов</h2>
    <p>3.1. Оплата производится в размере 100% предоплаты, если иное не согласовано письменно.</p>
    <p>3.2. Срок оплаты: в течение 3 (трёх) рабочих дней с даты подписания Договора.</p>
    <p>
      3.3. Обязательство по оплате считается исполненным в дату зачисления денежных средств на
      банковский счет Продавца (в т.ч. СБП/переводом).
    </p>
    <p>3.4. Реквизиты для оплаты указаны в разделе 14.</p>
    <p>
      3.5. При ошибках в реквизитах/назначении платежа Покупатель обязан немедленно уведомить Продавца;
      риск задержки исполнения в таком случае несёт Покупатель.
    </p>
    <p>
      3.6. Рекомендуемое назначение платежа (комментарий к переводу): «Оплата по договору
      №{{contract_number}} от {{created_date}} за товар по спецификации».
    </p>

    <h2>4. Сроки поставки, доставка</h2>
    <p>
      4.1. Срок передачи Товара Покупателю: не позднее {{delivery_term_days}} календарных дней
      {{delivery_term_basis}}.
    </p>
    <p>4.2. Город передачи/доставки: г. {{delivery_city_display}} (если иной — указывается в переписке/допсоглашении).</p>
    <p>4.3. Доставка осуществляется: {{delivery_cost_payer_label}}</p>
    <p>
      4.4. Способ доставки: {{delivery_method_label}}, если Стороны не согласовали иной способ
      письменно.
    </p>
    <p>4.5. Продавец обеспечивает упаковку, достаточную для перевозки.</p>
    <p>
      4.6. Если выдача через ТК/ПВЗ: Покупатель обязан забрать Товар в срок хранения ТК.
      Дополнительные расходы хранения/возврата по вине Покупателя оплачивает Покупатель.
    </p>

    <h2>5. Передача, приемка, документы</h2>
    <p>
      5.1. Факт передачи подтверждается подписанием: накладной/акта приема-передачи/документа ТК.
      При доставке через ТК/курьера/ПВЗ фактической передачей Товара считается вручение Товара
      Покупателю (или его уполномоченному представителю), подтвержденное документом ТК/курьера/ПВЗ.
    </p>
    <p>5.2. Право собственности переходит к Покупателю с момента фактической передачи Товара (п. 5.1).</p>
    <p>
      5.3. Риск случайной гибели/повреждения переходит к Покупателю с момента фактической передачи
      Товара (п. 5.1).
    </p>
    <p>5.4. При получении Покупатель обязан:</p>
    <p>а) осмотреть упаковку и Товар;</p>
    <p>
      б) при видимых повреждениях/вскрытии/недостаче — сделать отметки в документах ТК/акте и
      зафиксировать фото/видео.
    </p>
    <p>
      5.5. Претензии по количеству/комплектности/видимым повреждениям предъявляются в течение
      3 календарных дней с даты получения.
    </p>
    <p>5.6. Претензии по скрытым недостаткам — в пределах гарантийного срока (раздел 6).</p>
    <p>
      5.7. Вместе с Товаром Продавец передает документы (при наличии/применимости): гарантийный талон,
      инструкцию, документы ТК, документы об оплате.
    </p>

    <h2>6. Гарантия, сервис, возвраты</h2>
    <p>
      6.1. Гарантийный срок: 12 месяцев с даты передачи Товара, если больший срок не установлен
      производителем.
    </p>
    <p>
      6.2. Гарантия не распространяется на недостатки, возникшие вследствие нарушения эксплуатации,
      механических повреждений, попадания жидкости, несанкционированного ремонта, использования
      несовместимых аксессуаров, если это вызвало неисправность.
    </p>
    <p>
      6.3. Для обращения по гарантии Покупатель направляет Продавцу: описание проблемы, фото/видео,
      серийный номер, дату передачи, документы.
    </p>
    <p>
      6.4. Способ урегулирования: диагностика/ремонт/замена/возврат — по согласованию Сторон и
      применимым нормам закона.
    </p>
    <p>
      6.5. Доставка Товара до Продавца/сервисного центра и обратно при гарантийном обращении
      оплачивается Покупателем, если иное не согласовано Сторонами письменно.
    </p>
    <p>
      6.6. Срок диагностики и принятия решения по гарантийному обращению составляет 14 календарных
      дней с даты получения Товара Продавцом/сервисным центром, если иной срок не установлен
      применимым законом.
    </p>
    <p>
      6.7. Стороны подтверждают, что Покупатель приобретает Товар {{purchase_purpose_label}}.
    </p>
    <p>
      6.8. Ограничение: условия Договора не могут ограничивать права Покупателя, если на отношения
      распространяются императивные нормы (например, о защите прав потребителей — при покупке для
      личных нужд).
    </p>

    <h2>7. Замена модели / отсутствие товара (на случай “не привезли именно это”)</h2>
    <p>
      7.1. Если конкретная модель/комплектация из Спецификации стала недоступна (снята с
      производства/отсутствует у поставщиков), Продавец обязан в течение 5 рабочих дней уведомить
      Покупателя и предложить:
    </p>
    <p>а) аналог/эквивалент не хуже по ключевым характеристикам без доплаты либо</p>
    <p>б) аналог с доплатой/скидкой по соглашению Сторон, либо</p>
    <p>в) возврат 100% оплаты в течение 10 рабочих дней с даты согласования возврата.</p>
    <p>
      7.2. Замена допускается только с письменного согласия Покупателя (сообщение в мессенджере/почте
      подходит).
    </p>

    <h2>8. Ответственность сторон</h2>
    <p>8.1. За нарушение срока передачи Товара Продавец по требованию Покупателя:</p>
    <p>— либо передает Товар в дополнительный согласованный срок;</p>
    <p>— либо возвращает оплаченные средства при отказе Покупателя от Договора.</p>
    <p>
      8.2. Стороны освобождаются от ответственности за нарушение обязательств при форс-мажоре
      (раздел 10).
    </p>
    <p>
      8.3. Сторона, нарушившая обязательства, возмещает другой стороне документально подтвержденные
      убытки в пределах, допускаемых законом.
    </p>

    <h2>9. Порядок уведомлений и переписка</h2>
    <p>9.1. Уведомления направляются по телефону/e-mail/мессенджеру, указанным в реквизитах.</p>
    <p>
      9.2. Сообщения и согласования в переписке (мессенджер/почта) признаются юридически значимыми,
      если позволяют идентифицировать стороны (номер/аккаунт).
    </p>

    <h2>10. Форс-мажор</h2>
    <p>
      10.1. Форс-мажор: чрезвычайные и непредотвратимые обстоятельства (запреты властей, ЧС, военные
      действия, сбои логистики из-за санкций/закрытий и т.п.).
    </p>
    <p>10.2. Сторона уведомляет другую сторону в течение 5 календарных дней.</p>
    <p>
      10.3. Если форс-мажор длится более 30 календарных дней, любая сторона вправе предложить
      расторжение с взаиморасчетами.
    </p>

    <h2>11. Споры и досудебное урегулирование (“лучше решаем сами”)</h2>
    <p>11.1. Все споры Стороны стремятся урегулировать путем переговоров.</p>
    <p>
      11.2. Стороны направляют претензию в письменной форме; рекомендуемый срок ответа —
      10 календарных дней.
    </p>
    <p>
      11.3. При недостижении согласия спор передается в суд по правилам подсудности, установленным
      законом.
    </p>

    <h2>12. Конфиденциальность и запрет распространения договора</h2>
    <p>
      12.1. Конфиденциальной информацией по Договору являются: условия Договора и приложений, цена,
      скидки, сроки, реквизиты, персональные данные, переписка, документы поставки/логистики, а также
      иная информация, явно помеченная как конфиденциальная.
    </p>
    <p>
      12.2. Стороны обязуются не раскрывать и не передавать третьим лицам конфиденциальную информацию
      и сам Договор (в т.ч. сканы/фото), без предварительного письменного согласия другой Стороны.
    </p>
    <p>
      12.3. Стороны дают согласие на обработку и передачу персональных данных в объеме, необходимом
      для исполнения Договора, включая передачу банку/платежному агенту, ТК/курьеру/ПВЗ,
      сервисному центру/производителю, а также уполномоченным органам в случаях, предусмотренных
      законом.
    </p>
    <p>12.4. Исключения (разрешенное раскрытие): запрет п. 12.2 не применяется, если раскрытие необходимо:</p>
    <p>
      а) по требованию закона или по официальному запросу уполномоченных органов (включая суд,
      правоохранительные органы, ФНС и т.п.);
    </p>
    <p>
      б) для защиты прав Стороны в споре (досудебная претензия, суд, исполнительное производство);
    </p>
    <p>в) представителям Стороны на условиях конфиденциальности: адвокатам/юристам, бухгалтеру, аудитору;</p>
    <p>г) банку/платежному агенту для проведения платежа;</p>
    <p>д) транспортной компании/курьеру/ПВЗ — в объеме, необходимом для доставки;</p>
    <p>е) сервисному центру/производителю — в объеме, необходимом для гарантийного обслуживания.</p>
    <p>
      12.5. Если раскрытие допускается по п. 12.4 и законом не запрещено уведомление — Сторона заранее
      уведомляет другую Сторону о факте и объеме раскрытия.
    </p>
    <p>
      12.6. За нарушение конфиденциальности виновная Сторона уплачивает другой Стороне штраф
      {{confidentiality_penalty_amount_formatted}} и возмещает убытки сверх штрафа при наличии доказательств.
    </p>
    <p>
      12.7. Обязательства по конфиденциальности действуют 3 года после исполнения/расторжения Договора.
    </p>

    <p>
      <strong>Важно:</strong> даже самая жёсткая конфиденциальность не может запрещать исполнение
      требований госорганов, если они законны (поэтому исключение 12.4а обязательно).
    </p>

    <h2>13. Заключительные положения</h2>
    <p>13.1. Договор вступает в силу с момента подписания и действует до полного исполнения обязательств.</p>
    <p>
      13.2. Любые изменения — только в письменной форме, включая обмен подписанными сканами/фото.
    </p>
    <p>13.3. Недействительность одного условия не влияет на действительность остальных.</p>
    <p>13.4. Договор составлен в 2 экземплярах, по одному для каждой Стороны.</p>

    <h2>14. Реквизиты и подписи</h2>
    <table class="doc-table">
      <thead>
        <tr>
          <th style="width: 50%">
            {{#if supplier_is_ip}}Продавец (ИП){{/if}}
            {{#if supplier_is_person}}Продавец (физическое лицо){{/if}}
          </th>
          <th style="width: 50%">Покупатель</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            {{#if supplier_is_ip}}
              ИП: {{seller_ip_name}}<br />
              ОГРНИП: {{seller_ip_ogrnip_display}}<br />
              ИНН: {{seller_ip_inn_display}}<br />
              Адрес: {{supplier_address_display}}<br />
              р/с: {{supplier_checking_account_display}} в {{supplier_bank_name_display}}, БИК {{supplier_bik_display}},
              к/с {{supplier_correspondent_account_display}}<br />
              Тел.: {{supplier_phone_display}}<br />
              e-mail: {{supplier_email_display}}<br /><br />
              Подпись: _____________ / {{seller_ip_name}} /
            {{/if}}
            {{#if supplier_is_person}}
              ФИО: {{seller_person_full_name_display}}<br />
            {{/if}}
            {{#if seller_person_passport_line_visible}}Паспорт: {{seller_person_passport_display}}<br />{{/if}}
            {{#if seller_person_passport_issued_line_visible}}Выдан: {{seller_person_passport_issued_display}}<br />{{/if}}
            {{#if supplier_is_person}}
              Адрес: {{seller_person_address_display}}<br />
              Способ оплаты (СБП): {{seller_person_payment_details_display}}<br />
              Тел.: {{seller_person_phone_display}}<br />
              e-mail: {{seller_person_email_display}}<br /><br />
              Подпись: _____________ / {{seller_person_full_name_display}} /
            {{/if}}
          </td>
          <td>
            ФИО: {{buyer_person_full_name_display}}<br />
            {{#if buyer_person_has_passport}}Паспорт: {{buyer_person_passport_display}}<br />{{/if}}
            {{#if buyer_person_has_passport_issued}}Выдан: {{buyer_person_passport_issued_display}}<br />{{/if}}
            Адрес: {{buyer_person_address_display}}<br />
            Тел.: {{buyer_person_phone_display}}<br />
            e-mail: {{buyer_person_email_display}}<br /><br />
            Подпись: _____________ / {{buyer_person_full_name_display}} /
          </td>
        </tr>
      </tbody>
    </table>

    <h2>Приложение №1 — Спецификация</h2>
    <p>
      Примечание: в описании позиции рекомендуется указывать идентифицирующие признаки товара
      (модель, артикул, серийный номер, цвет/комплектация — при наличии).
    </p>
    <table class="doc-table">
      <thead>
        <tr>
          <th style="width: 8%">№</th>
          <th style="width: 42%">Наименование</th>
          <th style="width: 10%">Кол-во</th>
          <th style="width: 10%">Ед.</th>
          <th style="width: 15%">Цена за ед., руб.</th>
          <th style="width: 15%">Сумма, руб.</th>
        </tr>
      </thead>
      <tbody>
        {{#each items}}
          <tr>
            <td>{{index}}</td>
            <td>{{name}}</td>
            <td>{{qty}}</td>
            <td>{{unit}}</td>
            <td class="align-right">{{price}}</td>
            <td class="align-right">{{line_total}}</td>
          </tr>
        {{/each}}
      </tbody>
    </table>
    <p class="summary">Итого: {{total_amount_formatted}}</p>
    <table style="width: 100%; border-collapse: collapse; margin-top: 12pt;">
      <tbody>
        <tr>
          <td style="width: 50%; border: none; padding: 0 8pt 0 0; vertical-align: top;">
            {{#if supplier_is_ip}}Продавец _____________ / {{seller_ip_name}} /{{/if}}
            {{#if supplier_is_person}}Продавец _____________ / {{seller_person_full_name_display}} /{{/if}}
          </td>
          <td style="width: 50%; border: none; padding: 0 0 0 8pt; vertical-align: top;">
            Покупатель _____________ / {{buyer_person_full_name_display}} /
          </td>
        </tr>
      </tbody>
    </table>
  </div>
`;

const DEFAULT_DATA = {
  counterparties: [
    {
      id: '1',
      name: 'ООО "ТехноСолюшнс"',
      legalType: 'ooo',
      inn: '7701234567',
      kpp: '770101001',
      ogrn: '1127746000001',
      address: '123000, г. Москва, ул. Инновационная, д. 1',
      contactPerson: 'Иванов Иван',
      directorName: 'Иванов Иван Иванович',
      email: 'ivanov@techsol.ru',
      bankName: 'ПАО "Сбербанк"',
      bik: '044525225',
      correspondentAccount: '30101810400000000225',
      checkingAccount: '40702810938000000000',
      bankAccounts: [
        {
          bankName: 'ПАО "Сбербанк"',
          bik: '044525225',
          correspondentAccount: '30101810400000000225',
          checkingAccount: '40702810938000000000',
        },
      ],
    },
    {
      id: '2',
      name: 'АО "Глобал Логистик"',
      legalType: 'ooo',
      inn: '7709876543',
      kpp: '781201001',
      ogrn: '1027800000002',
      address: '190000, г. Санкт-Петербург, Невский пр-т, д. 45',
      contactPerson: 'Смирнова Анна',
      directorName: 'Смирнова Анна Павловна',
      email: 'smirnova@globallog.ru',
      bankName: 'Банк ВТБ (ПАО)',
      bik: '044525411',
      correspondentAccount: '30101810145250000411',
      checkingAccount: '40702810200000000002',
      bankAccounts: [
        {
          bankName: 'Банк ВТБ (ПАО)',
          bik: '044525411',
          correspondentAccount: '30101810145250000411',
          checkingAccount: '40702810200000000002',
        },
      ],
    },
    {
      id: '3',
      name: 'Петров Петр Петрович',
      legalType: 'ip',
      inn: '5029384756',
      ogrnip: '315500000000003',
      address: '141400, г. Химки, ул. Ленина, д. 5',
      contactPerson: 'Петров Петр',
      email: 'petrov@design.ru',
      bankName: 'АО "Альфа-Банк"',
      bik: '044525593',
      correspondentAccount: '30101810200000000593',
      checkingAccount: '40802810900000000003',
      bankAccounts: [
        {
          bankName: 'АО "Альфа-Банк"',
          bik: '044525593',
          correspondentAccount: '30101810200000000593',
          checkingAccount: '40802810900000000003',
        },
      ],
    },
  ],
  invoices: [
    {
      id: 'inv-001',
      number: 'СЧ-2023-001',
      date: '25.10.2023',
      amount: 500000,
      currency: 'RUB',
      status: 'Не оплачен',
      commissionPercent: 6,
      counterpartyId: '1',
      items: [
        {
          id: 'i1',
          description: 'Разработка веб-сайта (этап 1)',
          quantity: 1,
          price: 500000,
          unit: 'Проект',
        },
      ],
    },
    {
      id: 'inv-002',
      number: 'СЧ-2023-002',
      date: '26.10.2023',
      amount: 120000,
      currency: 'RUB',
      status: 'Оплачен',
      commissionPercent: 6,
      counterpartyId: '2',
      items: [
        {
          id: 'i2',
          description: 'Техническая поддержка серверов',
          quantity: 12,
          price: 10000,
          unit: 'Час',
        },
      ],
    },
    {
      id: 'inv-003',
      number: 'СЧ-2023-003',
      date: '27.10.2023',
      amount: 85000,
      currency: 'RUB',
      status: 'Не оплачен',
      commissionPercent: 6,
      counterpartyId: '3',
      items: [
        {
          id: 'i3',
          description: 'Консультационные услуги',
          quantity: 5,
          price: 17000,
          unit: 'Час',
        },
      ],
    },
  ],
  templates: [
    {
      id: 't1',
      name: 'Договор поставки с НДС',
      type: CONTRACT_TYPE.SUPPLY,
      version: '2.2',
      updatedAt: '18.02.2026',
      isActive: true,
      content: SUPPLY_WITH_VAT_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    },
    {
      id: 't2',
      name: 'Договор об уровне сервиса (SLA)',
      type: CONTRACT_TYPE.SERVICE,
      version: '1.5',
      updatedAt: '15.10.2023',
      isActive: true,
      content: DEFAULT_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    },
    {
      id: 't3',
      name: 'Соглашение о конфиденциальности (NDA)',
      type: CONTRACT_TYPE.NDA,
      version: '3.0',
      updatedAt: '01.09.2023',
      isActive: true,
      content: DEFAULT_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    },
    {
      id: 't4',
      name: 'Договор аренды оборудования',
      type: CONTRACT_TYPE.RENTAL,
      version: '1.0',
      updatedAt: '12.08.2023',
      isActive: true,
      content: DEFAULT_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    },
    {
      id: 't5',
      name: 'Договор купли-продажи товара (расширенный, конфиденциальность)',
      type: CONTRACT_TYPE.SUPPLY,
      version: '1.3',
      updatedAt: '25.02.2026',
      isActive: true,
      content: GOODS_SALE_EXTENDED_CONFIDENTIALITY_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    },
  ],
  contracts: [
    {
      id: 'c1',
      number: 'Д-2023-085',
      title: 'Разработка сайта для ООО "ТехноСолюшнс"',
      type: CONTRACT_TYPE.SERVICE,
      counterparty: {
        id: '1',
        name: 'ООО "ТехноСолюшнс"',
        legalType: 'ooo',
        inn: '7701234567',
        kpp: '770101001',
        ogrn: '1127746000001',
        address: '123000, г. Москва, ул. Инновационная, д. 1',
        contactPerson: 'Иванов Иван',
        directorName: 'Иванов Иван Иванович',
        email: 'ivanov@techsol.ru',
        bankName: 'ПАО "Сбербанк"',
        bik: '044525225',
        correspondentAccount: '30101810400000000225',
        checkingAccount: '40702810938000000000',
        bankAccounts: [
          {
            bankName: 'ПАО "Сбербанк"',
            bik: '044525225',
            correspondentAccount: '30101810400000000225',
            checkingAccount: '40702810938000000000',
          },
        ],
      },
      status: CONTRACT_STATUS.DRAFT,
      createdAt: '26.10.2023',
      amount: 500000,
      invoiceId: 'inv-001',
      paymentTerms: 10,
      includeDelivery: true,
      deliveryDate: null,
      vatRate: DEFAULT_CONTRACT_PRICING.vatRate,
      vatMode: DEFAULT_CONTRACT_PRICING.vatMode,
      markupPercent: DEFAULT_CONTRACT_PRICING.markupPercent,
      markupMode: DEFAULT_CONTRACT_PRICING.markupMode,
      markupCalcMode: DEFAULT_CONTRACT_PRICING.markupCalcMode,
    },
    {
      id: 'c2',
      number: 'Д-2023-084',
      title: 'Поставка логистического ПО',
      type: CONTRACT_TYPE.SUPPLY,
      counterparty: {
        id: '2',
        name: 'АО "Глобал Логистик"',
        legalType: 'ooo',
        inn: '7709876543',
        kpp: '781201001',
        ogrn: '1027800000002',
        address: '190000, г. Санкт-Петербург, Невский пр-т, д. 45',
        contactPerson: 'Смирнова Анна',
        directorName: 'Смирнова Анна Павловна',
        email: 'smirnova@globallog.ru',
        bankName: 'Банк ВТБ (ПАО)',
        bik: '044525411',
        correspondentAccount: '30101810145250000411',
        checkingAccount: '40702810200000000002',
        bankAccounts: [
          {
            bankName: 'Банк ВТБ (ПАО)',
            bik: '044525411',
            correspondentAccount: '30101810145250000411',
            checkingAccount: '40702810200000000002',
          },
        ],
      },
      status: CONTRACT_STATUS.SIGNED,
      createdAt: '20.10.2023',
      amount: 1500000,
      paymentTerms: 15,
      includeDelivery: true,
      deliveryDate: null,
      vatRate: DEFAULT_CONTRACT_PRICING.vatRate,
      vatMode: DEFAULT_CONTRACT_PRICING.vatMode,
      markupPercent: DEFAULT_CONTRACT_PRICING.markupPercent,
      markupMode: DEFAULT_CONTRACT_PRICING.markupMode,
      markupCalcMode: DEFAULT_CONTRACT_PRICING.markupCalcMode,
    },
    {
      id: 'c3',
      number: 'Д-2023-083',
      title: 'NDA с Петров Петр Петрович',
      type: CONTRACT_TYPE.NDA,
      counterparty: {
        id: '3',
        name: 'Петров Петр Петрович',
        legalType: 'ip',
        inn: '5029384756',
        ogrnip: '315500000000003',
        address: '141400, г. Химки, ул. Ленина, д. 5',
        contactPerson: 'Петров Петр',
        email: 'petrov@design.ru',
        bankName: 'АО "Альфа-Банк"',
        bik: '044525593',
        correspondentAccount: '30101810200000000593',
        checkingAccount: '40802810900000000003',
        bankAccounts: [
          {
            bankName: 'АО "Альфа-Банк"',
            bik: '044525593',
            correspondentAccount: '30101810200000000593',
            checkingAccount: '40802810900000000003',
          },
        ],
      },
      status: CONTRACT_STATUS.PENDING_APPROVAL,
      createdAt: '18.10.2023',
      paymentTerms: 10,
      includeDelivery: false,
      deliveryDate: null,
      vatRate: DEFAULT_CONTRACT_PRICING.vatRate,
      vatMode: DEFAULT_CONTRACT_PRICING.vatMode,
      markupPercent: DEFAULT_CONTRACT_PRICING.markupPercent,
      markupMode: DEFAULT_CONTRACT_PRICING.markupMode,
      markupCalcMode: DEFAULT_CONTRACT_PRICING.markupCalcMode,
    },
  ],
  settings: {
    legalType: 'ooo',
    companyName: 'ООО "Моя Компания"',
    inn: '7701234567',
    kpp: '770101001',
    ogrn: '1127746000000',
    ogrnip: '',
    directorGenitive: 'Иванова Ивана Ивановича',
    legalAddress: '123000, г. Москва, Пресненская наб., д. 12',
    email: 'docs@mycompany.ru',
    phone: '+7 (495) 123-45-67',
    bankName: 'ПАО "Сбербанк"',
    bik: '044525225',
    correspondentAccount: '30101810400000000225',
    checkingAccount: '40702810938000000000',
    bankAccounts: [
      {
        bankName: 'ПАО "Сбербанк"',
        bik: '044525225',
        correspondentAccount: '30101810400000000225',
        checkingAccount: '40702810938000000000',
      },
    ],
    companyProfiles: [
      {
        id: 'company-1',
        legalType: 'ooo',
        companyName: 'ООО "Моя Компания"',
        inn: '7701234567',
        kpp: '770101001',
        ogrn: '1127746000000',
        ogrnip: '',
        directorGenitive: 'Иванова Ивана Ивановича',
        legalAddress: '123000, г. Москва, Пресненская наб., д. 12',
        email: 'docs@mycompany.ru',
        phone: '+7 (495) 123-45-67',
        bankName: 'ПАО "Сбербанк"',
        bik: '044525225',
        correspondentAccount: '30101810400000000225',
        checkingAccount: '40702810938000000000',
        bankAccounts: [
          {
            bankName: 'ПАО "Сбербанк"',
            bik: '044525225',
            correspondentAccount: '30101810400000000225',
            checkingAccount: '40702810938000000000',
          },
        ],
      },
    ],
    activeCompanyProfileId: 'company-1',
    privateSellerRf: {
      fullName: '',
      passportSeries: '',
      passportNumber: '',
      passportIssuedBy: '',
      passportIssuedDate: '',
      passportDepartmentCode: '',
      registrationAddress: '',
      residenceAddress: '',
      phone: '',
      email: '',
      bankName: '',
      cardNumber: '',
      sbpPhone: '',
      bik: '',
      checkingAccount: '',
      correspondentAccount: '',
    },
    defaultCurrency: 'RUB',
    autoNumbering: true,
  },
};

const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8' };
let updateChain = Promise.resolve();
let db = null;

class ApiError extends Error {
  constructor(statusCode, message) {
    super(message);
    this.statusCode = statusCode;
  }
}

app.use(
  cors({
    origin: process.env.CORS_ORIGIN ? process.env.CORS_ORIGIN.split(',') : true,
  })
);
app.use(express.json({ limit: JSON_LIMIT }));
app.get('/favicon.ico', (_req, res) => {
  res.status(204).end();
});

const asyncHandler = (handler) => (req, res, next) =>
  Promise.resolve(handler(req, res, next)).catch(next);

const deepClone = (value) => JSON.parse(JSON.stringify(value));

const ensureDataFile = async () => {
  try {
    await fs.access(DATA_FILE);
  } catch {
    await fs.writeFile(DATA_FILE, JSON.stringify(DEFAULT_DATA, null, 2), 'utf8');
  }
};

const normalizeData = (rawData) => {
  const merged = { ...DEFAULT_DATA, ...rawData };

  const sourceCounterparties = Array.isArray(rawData?.counterparties)
    ? rawData.counterparties
    : deepClone(DEFAULT_DATA.counterparties);
  merged.counterparties = sourceCounterparties.map((counterparty) => {
    const bankAccounts = normalizeBankAccounts(counterparty?.bankAccounts, counterparty);
    const primaryBankAccount = getPrimaryBankAccount(bankAccounts, counterparty);
    return {
      ...counterparty,
      bankAccounts,
      bankName: primaryBankAccount.bankName,
      checkingAccount: primaryBankAccount.checkingAccount,
      correspondentAccount: primaryBankAccount.correspondentAccount,
      bik: primaryBankAccount.bik,
    };
  });
  merged.invoices = Array.isArray(rawData?.invoices) ? rawData.invoices : deepClone(DEFAULT_DATA.invoices);
  merged.templates = Array.isArray(rawData?.templates) ? rawData.templates : deepClone(DEFAULT_DATA.templates);
  merged.contracts = Array.isArray(rawData?.contracts) ? rawData.contracts : deepClone(DEFAULT_DATA.contracts);
  merged.settings = normalizeSettingsPayload(rawData?.settings);

  return merged;
};

const readData = async () => {
  await ensureDataFile();
  const raw = await fs.readFile(DATA_FILE, 'utf8');

  try {
    const parsed = JSON.parse(raw);
    return normalizeData(parsed);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Failed to parse ${DATA_FILE}: ${message}`);
    await fs.writeFile(DATA_FILE, JSON.stringify(DEFAULT_DATA, null, 2), 'utf8');
    return deepClone(DEFAULT_DATA);
  }
};

const withDataLock = async (operation) => {
  const next = updateChain.then(operation, operation);
  updateChain = next.catch(() => undefined);
  return next;
};

const formatDate = (date = new Date()) =>
  date.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;

const sanitizeFileName = (value, fallback) => {
  if (!isNonEmptyString(value)) {
    return fallback;
  }

  const safe = value.replace(/[^a-zA-Z0-9а-яА-Я._-]/g, '_');
  return safe.length > 0 ? safe : fallback;
};

const toAsciiFileName = (value, fallback) => {
  if (!isNonEmptyString(value)) {
    return fallback;
  }

  const safe = value
    .normalize('NFKD')
    .replace(/[^\x20-\x7E]/g, '_')
    .replace(/[^a-zA-Z0-9._-]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');

  return safe.length > 0 ? safe : fallback;
};

const encodeRFC5987 = (value) =>
  encodeURIComponent(value).replace(/['()*]/g, (symbol) => `%${symbol.charCodeAt(0).toString(16).toUpperCase()}`);

const buildContentDisposition = (baseName, extension, fallbackBaseName = 'contract') => {
  const unicodeFileName = `${baseName}.${extension}`;
  const asciiFileName = `${toAsciiFileName(baseName, fallbackBaseName)}.${extension}`;
  return `attachment; filename="${asciiFileName}"; filename*=UTF-8''${encodeRFC5987(unicodeFileName)}`;
};

const resolvePuppeteerHeadlessMode = () => {
  const requested = String(process.env.PUPPETEER_HEADLESS_MODE || '').trim().toLowerCase();
  if (!requested) {
    return 'new';
  }

  if (requested === 'new') {
    return 'new';
  }

  if (requested === 'old' || requested === 'legacy' || requested === 'true' || requested === '1') {
    return true;
  }

  if (requested === 'false' || requested === '0' || requested === 'off') {
    return false;
  }

  return 'new';
};

const buildPuppeteerLaunchOptions = () => {
  const launchOptions = {
    headless: resolvePuppeteerHeadlessMode(),
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  };

  if (isNonEmptyString(process.env.PUPPETEER_EXECUTABLE_PATH)) {
    launchOptions.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
  }

  if (process.env.PUPPETEER_BROWSER === 'chrome') {
    launchOptions.channel = 'chrome';
  }

  if (!launchOptions.executablePath) {
    const platform = process.platform;
    const candidates =
      platform === 'darwin'
        ? [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
          ]
        : platform === 'win32'
          ? [
              'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
              'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
              'C:\\Program Files\\Chromium\\Application\\chrome.exe',
            ]
          : [
              '/usr/bin/google-chrome',
              '/usr/bin/google-chrome-stable',
              '/usr/bin/chromium-browser',
              '/usr/bin/chromium',
            ];

    const detectedExecutable = candidates.find((candidate) => fsSync.existsSync(candidate));
    if (detectedExecutable) {
      launchOptions.executablePath = detectedExecutable;
    }
  }

  return launchOptions;
};

const renderPdfBufferWithPuppeteer = async (browser, html, css) => {
  const documentHtml = fullHtmlDocument(html, css);
  const attempts = [
    { waitUntil: 'networkidle0', timeout: 45000 },
    { waitUntil: 'domcontentloaded', timeout: 30000 },
  ];
  let lastError;

  for (let index = 0; index < attempts.length; index += 1) {
    let page;
    try {
      page = await browser.newPage();
      const attempt = attempts[index];
      await page.setContent(documentHtml, { waitUntil: attempt.waitUntil, timeout: attempt.timeout });
      await page.emulateMediaType('screen');
      await page.evaluate(async () => {
        if (document.fonts && document.fonts.ready) {
          try {
            await document.fonts.ready;
          } catch {
            // ignore font readiness issues and continue PDF rendering
          }
        }
      });
      return await page.pdf({
        format: 'A4',
        printBackground: true,
        margin: {
          top: '18mm',
          right: '15mm',
          bottom: '18mm',
          left: '15mm',
        },
      });
    } catch (error) {
      lastError = error;
      const shouldRetry = index < attempts.length - 1;
      if (!shouldRetry) {
        break;
      }

      const reason = error instanceof Error ? error.message : String(error);
      console.warn(`PDF render retry (${index + 1}/${attempts.length}) after error: ${reason}`);
    } finally {
      if (page) {
        try {
          await page.close();
        } catch {
          // ignore page close errors (frame may already be detached)
        }
      }
    }
  }

  throw lastError || new Error('Не удалось сформировать PDF.');
};

const toPositiveInteger = (value, fallback = 0) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.trunc(parsed);
};

const toNonNegativeNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback;
  }
  return parsed;
};

const toInvoiceStatus = (value) => {
  const normalized = String(value ?? '').trim();
  if (VALID_INVOICE_STATUSES.has(normalized)) {
    return normalized;
  }

  return 'Не оплачен';
};

const toContractStatus = (value, fallback = CONTRACT_STATUS.DRAFT) => {
  const normalized = String(value ?? '').trim();
  if (VALID_CONTRACT_STATUSES.has(normalized)) {
    return normalized;
  }

  return VALID_CONTRACT_STATUSES.has(fallback) ? fallback : CONTRACT_STATUS.DRAFT;
};

const toCurrency = (value) => {
  if (!isNonEmptyString(value)) {
    return 'RUB';
  }

  return value.trim().toUpperCase();
};

const toCounterpartyType = (value, fallbackName = '') => {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (VALID_COUNTERPARTY_TYPES.has(normalized)) {
    return normalized;
  }

  const name = String(fallbackName || '').trim().toLowerCase();
  if (name.startsWith('ип ') || name.includes('индивидуальный предприниматель')) {
    return 'ip';
  }
  if (name.startsWith('ао ')) {
    return 'ao';
  }
  if (name.startsWith('физ ') || name.includes('физическое лицо')) {
    return 'person';
  }

  return 'ooo';
};

const toTrimmedString = (value) => (isNonEmptyString(value) ? value.trim() : '');
const pickContractDataString = (contractData, ...keys) => {
  for (const key of keys) {
    const value = toTrimmedString(contractData?.[key]);
    if (value) {
      return value;
    }
  }
  return '';
};

const EMPTY_BANK_ACCOUNT = Object.freeze({
  bankName: '',
  checkingAccount: '',
  correspondentAccount: '',
  bik: '',
  cardNumber: '',
  sbpPhone: '',
});

const normalizeBankAccount = (value) => ({
  bankName: toTrimmedString(value?.bankName),
  checkingAccount: toTrimmedString(value?.checkingAccount),
  correspondentAccount: toTrimmedString(value?.correspondentAccount),
  bik: toTrimmedString(value?.bik),
  cardNumber: toTrimmedString(value?.cardNumber),
  sbpPhone: toTrimmedString(value?.sbpPhone),
});

const hasBankAccountValues = (value) =>
  Boolean(
    value?.bankName ||
      value?.checkingAccount ||
      value?.correspondentAccount ||
      value?.bik ||
      value?.cardNumber ||
      value?.sbpPhone
  );

const toSupplierBankAccount = (value) => {
  const normalized = normalizeBankAccount(value);
  return hasBankAccountValues(normalized) ? normalized : undefined;
};

const normalizeBankAccounts = (value, fallback = {}) => {
  if (Array.isArray(value)) {
    const normalized = value.map((account) => normalizeBankAccount(account)).filter(hasBankAccountValues);
    if (normalized.length > 0) {
      return normalized;
    }
  }

  const normalizedFallback = normalizeBankAccount(fallback);
  if (hasBankAccountValues(normalizedFallback)) {
    return [normalizedFallback];
  }

  return [];
};

const getPrimaryBankAccount = (value, fallback = {}) => {
  const normalized = normalizeBankAccounts(value, fallback);
  return normalized[0] || EMPTY_BANK_ACCOUNT;
};

const getCounterpartyFormalName = (counterparty) => {
  const legalType = toCounterpartyType(counterparty?.legalType, counterparty?.name);
  const name = toTrimmedString(counterparty?.name);
  if (!name) {
    return 'контрагент';
  }

  if (legalType === 'ip') {
    return /^ип\s+/i.test(name) ? name : `ИП ${name}`;
  }

  return name;
};

const normalizeInvoiceItems = (items) => {
  if (!Array.isArray(items)) {
    return [];
  }

  return items.map((item, index) => ({
    id: isNonEmptyString(item?.id) ? item.id : `ii-${Date.now()}-${index}-${Math.floor(Math.random() * 1000)}`,
    description: isNonEmptyString(item?.description) ? item.description.trim() : `Позиция ${index + 1}`,
    quantity: toNonNegativeNumber(item?.quantity, 0),
    price: toNonNegativeNumber(item?.price, 0),
    unit: isNonEmptyString(item?.unit) ? item.unit.trim() : 'шт',
  }));
};

const toVatRate = (value) => {
  const normalized = String(value ?? '').trim();
  if (VALID_VAT_RATES.has(normalized)) {
    return normalized;
  }
  return DEFAULT_CONTRACT_PRICING.vatRate;
};

const toVatMode = (value) => {
  const normalized = String(value ?? '').trim();
  if (VALID_VAT_MODES.has(normalized)) {
    return normalized;
  }
  return DEFAULT_CONTRACT_PRICING.vatMode;
};

const toMarkupMode = (value) => {
  const normalized = String(value ?? '').trim();
  if (VALID_MARKUP_MODES.has(normalized)) {
    return normalized;
  }
  return DEFAULT_CONTRACT_PRICING.markupMode;
};

const toMarkupCalcMode = (value) => {
  const normalized = String(value ?? '').trim();
  if (VALID_MARKUP_CALC_MODES.has(normalized)) {
    return normalized;
  }
  return DEFAULT_CONTRACT_PRICING.markupCalcMode;
};

const toMarkupPercent = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return DEFAULT_CONTRACT_PRICING.markupPercent;
  }

  return Math.min(parsed, 1000);
};

const buildContractTitle = (type, counterparty) => {
  const formalName = getCounterpartyFormalName(counterparty);
  if (type === CONTRACT_TYPE.NDA) {
    return `NDA с ${formalName}`;
  }
  return `${type} с ${formalName}`;
};

const formatMoney = (value) =>
  `${toNonNegativeNumber(value, 0).toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ₽`;

const parseRuDateToDate = (value) => {
  if (!isNonEmptyString(value)) {
    return new Date();
  }

  const [day, month, year] = value.split('.').map(Number);
  if (!day || !month || !year) {
    return new Date();
  }

  const parsed = new Date(year, month - 1, day);
  if (Number.isNaN(parsed.getTime())) {
    return new Date();
  }

  return parsed;
};

const extractCityFromAddress = (address) => {
  const normalized = toTrimmedString(address);
  if (!normalized) {
    return 'Москва';
  }

  const cityMatch = normalized.match(/г\.\s*([^,]+)/i);
  if (cityMatch && isNonEmptyString(cityMatch[1])) {
    return cityMatch[1].trim();
  }

  return normalized.split(',')[0]?.trim() || 'Москва';
};

const stripIpPrefix = (value) =>
  toTrimmedString(value)
    .replace(/^ип\s+/i, '')
    .replace(/^индивидуальный предприниматель\s+/i, '')
    .trim();

const pluralRu = (value, [one, few, many]) => {
  const abs = Math.abs(Number(value) || 0);
  const mod100 = abs % 100;
  if (mod100 >= 11 && mod100 <= 19) {
    return many;
  }
  const mod10 = abs % 10;
  if (mod10 === 1) {
    return one;
  }
  if (mod10 >= 2 && mod10 <= 4) {
    return few;
  }
  return many;
};

const RU_UNITS = {
  male: ['ноль', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'],
  female: ['ноль', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'],
};
const RU_TEENS = [
  'десять',
  'одиннадцать',
  'двенадцать',
  'тринадцать',
  'четырнадцать',
  'пятнадцать',
  'шестнадцать',
  'семнадцать',
  'восемнадцать',
  'девятнадцать',
];
const RU_TENS = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто'];
const RU_HUNDREDS = [
  '',
  'сто',
  'двести',
  'триста',
  'четыреста',
  'пятьсот',
  'шестьсот',
  'семьсот',
  'восемьсот',
  'девятьсот',
];
const RU_GROUPS = [
  { value: 1000000000, gender: 'male', forms: ['миллиард', 'миллиарда', 'миллиардов'] },
  { value: 1000000, gender: 'male', forms: ['миллион', 'миллиона', 'миллионов'] },
  { value: 1000, gender: 'female', forms: ['тысяча', 'тысячи', 'тысяч'] },
];

const triadToWordsRu = (value, gender = 'male') => {
  const num = Math.trunc(Math.abs(Number(value) || 0)) % 1000;
  if (num === 0) {
    return '';
  }

  const chunks = [];
  const hundreds = Math.trunc(num / 100);
  const tensUnits = num % 100;
  const tens = Math.trunc(tensUnits / 10);
  const units = tensUnits % 10;

  if (hundreds > 0) {
    chunks.push(RU_HUNDREDS[hundreds]);
  }

  if (tensUnits >= 10 && tensUnits <= 19) {
    chunks.push(RU_TEENS[tensUnits - 10]);
  } else {
    if (tens > 1) {
      chunks.push(RU_TENS[tens]);
    }
    if (units > 0) {
      chunks.push((gender === 'female' ? RU_UNITS.female : RU_UNITS.male)[units]);
    }
  }

  return chunks.join(' ').trim();
};

const numberToWordsRu = (value) => {
  let num = Math.trunc(toNonNegativeNumber(value, 0));
  if (num === 0) {
    return 'ноль';
  }

  const chunks = [];

  RU_GROUPS.forEach((group) => {
    const groupCount = Math.trunc(num / group.value);
    if (groupCount > 0) {
      const words = triadToWordsRu(groupCount, group.gender);
      chunks.push(words, pluralRu(groupCount, group.forms));
      num %= group.value;
    }
  });

  if (num > 0) {
    chunks.push(triadToWordsRu(num, 'male'));
  }

  return chunks.filter(Boolean).join(' ').trim();
};

const amountToRublesWords = (value) => {
  const normalized = toNonNegativeNumber(value, 0);
  const rubles = Math.trunc(normalized);
  const kopecks = Math.round((normalized - rubles) * 100);
  const safeKopecks = kopecks === 100 ? 0 : kopecks;
  const safeRubles = kopecks === 100 ? rubles + 1 : rubles;
  const rublesWords = `${numberToWordsRu(safeRubles)} ${pluralRu(safeRubles, ['рубль', 'рубля', 'рублей'])}`;
  const kopecksText = String(safeKopecks).padStart(2, '0');
  const full = `${rublesWords} ${kopecksText} ${pluralRu(safeKopecks, ['копейка', 'копейки', 'копеек'])}`;

  return {
    rubles: safeRubles,
    kopecks: safeKopecks,
    words: rublesWords,
    full,
  };
};

const estimateVatAmountFromTotal = ({ totalAmountRaw, vatRate, vatMode }) => {
  const total = toNonNegativeNumber(totalAmountRaw, 0);
  const normalizedVatRate = toVatRate(vatRate);
  const normalizedVatMode = toVatMode(vatMode);
  if (normalizedVatRate === 'none' || normalizedVatRate === '0') {
    return 0;
  }

  const rate = Number(normalizedVatRate);
  if (!Number.isFinite(rate) || rate <= 0) {
    return 0;
  }

  // `totalAmountRaw` is a final contract total in current flow. For both "included" and "on_top"
  // modes we show a stable estimate of the VAT amount from the gross total.
  if (normalizedVatMode === 'included' || normalizedVatMode === 'on_top') {
    return Math.round(((total * rate) / (100 + rate)) * 100) / 100;
  }

  return 0;
};

const buildGoodsSaleVatClauseText = ({ totalAmountRaw, vatRate, vatMode, supplierTaxBasis, supplierType }) => {
  const normalizedVatRate = toVatRate(vatRate);
  const normalizedVatMode = toVatMode(vatMode);
  const taxBasis = toTrimmedString(supplierTaxBasis);
  const estimatedVat = estimateVatAmountFromTotal({
    totalAmountRaw,
    vatRate: normalizedVatRate,
    vatMode: normalizedVatMode,
  });

  if (normalizedVatRate === 'none') {
    if (toTrimmedString(supplierType) === 'person') {
      return 'НДС не начисляется.';
    }
    return `НДС не применяется в связи с применением Поставщиком ${taxBasis || 'УСН (без НДС)'}.`;
  }

  if (normalizedVatRate === '0') {
    return 'Применяется ставка НДС 0%.';
  }

  if (normalizedVatMode === 'included') {
    return `Стоимость товара включает НДС ${normalizedVatRate}% в размере ${formatMoney(estimatedVat)}.`;
  }

  return `НДС ${normalizedVatRate}% начисляется сверх стоимости товара и составляет ${formatMoney(estimatedVat)}.`;
};

const escapeHtml = (value) =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const getTemplateValue = (context, path) => {
  const normalizedPath = toTrimmedString(path);
  if (!normalizedPath) {
    return undefined;
  }

  if (normalizedPath === 'this') {
    return context.this;
  }

  if (normalizedPath === '@index') {
    return context['@index'];
  }

  if (Object.prototype.hasOwnProperty.call(context, normalizedPath)) {
    return context[normalizedPath];
  }

  return normalizedPath.split('.').reduce((acc, chunk) => {
    if (acc == null || typeof acc !== 'object') {
      return undefined;
    }
    return acc[chunk];
  }, context);
};

const renderTemplateContent = (source, context) => {
  if (!isNonEmptyString(source)) {
    return '';
  }

  let result = source;

  result = result.replace(/{{#each\s+([a-zA-Z0-9_.@]+)}}([\s\S]*?){{\/each}}/g, (_match, path, block) => {
    const value = getTemplateValue(context, path);
    if (!Array.isArray(value) || value.length === 0) {
      return '';
    }

    return value
      .map((entry, index) => {
        const rowContext =
          entry && typeof entry === 'object'
            ? {
                ...context,
                ...entry,
                this: entry,
                '@index': index,
                index: index + 1,
              }
            : {
                ...context,
                this: entry,
                '@index': index,
                index: index + 1,
              };

        return renderTemplateContent(block, rowContext);
      })
      .join('');
  });

  result = result.replace(/{{#if\s+([a-zA-Z0-9_.@]+)}}([\s\S]*?){{\/if}}/g, (_match, path, block) => {
    const value = getTemplateValue(context, path);
    if (Array.isArray(value)) {
      return value.length > 0 ? renderTemplateContent(block, context) : '';
    }

    return value ? renderTemplateContent(block, context) : '';
  });

  result = result.replace(/{{\s*([a-zA-Z0-9_.@]+)\s*}}/g, (_match, path) => {
    const value = getTemplateValue(context, path);
    if (value == null) {
      return '';
    }

    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }

    return escapeHtml(String(value));
  });

  return result;
};

const normalizeTemplateVariables = (value) => {
  if (!Array.isArray(value) || value.length === 0) {
    return deepClone(DEFAULT_TEMPLATE_VARIABLES);
  }

  return value
    .map((variable) => ({
      key: toTrimmedString(variable?.key),
      description: toTrimmedString(variable?.description),
      sourceTable: toTrimmedString(variable?.sourceTable || variable?.source_table),
    }))
    .filter((variable) => isNonEmptyString(variable.key));
};

const normalizeTemplateContent = (value) => (isNonEmptyString(value) ? value : DEFAULT_TEMPLATE_CONTENT);

const normalizeTemplateCss = (value) => (isNonEmptyString(value) ? value : DEFAULT_TEMPLATE_CSS);

const resolveSupplierProfileFromSettings = (settings, preferredProfileId) => {
  if (!settings || typeof settings !== 'object') {
    return {};
  }

  if (Array.isArray(settings.companyProfiles) && settings.companyProfiles.length > 0) {
    const requestedId = toTrimmedString(preferredProfileId) || toTrimmedString(settings.activeCompanyProfileId);
    const selectedProfile = settings.companyProfiles.find((profile) => profile.id === requestedId) || settings.companyProfiles[0];
    if (selectedProfile && typeof selectedProfile === 'object') {
      return selectedProfile;
    }
  }

  return {
    legalType: settings.legalType,
    companyName: settings.companyName,
    inn: settings.inn,
    kpp: settings.kpp,
    ogrn: settings.ogrn,
    ogrnip: settings.ogrnip,
    directorGenitive: settings.directorGenitive,
    legalAddress: settings.legalAddress,
    email: settings.email,
    phone: settings.phone,
    bankName: settings.bankName,
    cardNumber: settings.cardNumber,
    sbpPhone: settings.sbpPhone,
    checkingAccount: settings.checkingAccount,
    correspondentAccount: settings.correspondentAccount,
    bik: settings.bik,
    bankAccounts: settings.bankAccounts,
    passportSeries: settings.passportSeries,
    passportNumber: settings.passportNumber,
    passportIssuedBy: settings.passportIssuedBy,
    passportIssuedDate: settings.passportIssuedDate,
    passportDepartmentCode: settings.passportDepartmentCode,
    registrationAddress: settings.registrationAddress,
    residenceAddress: settings.residenceAddress,
  };
};

const normalizePrivatePersonRfProfile = (value) => {
  const source = value && typeof value === 'object' ? value : {};
  return {
    fullName: toTrimmedString(source.fullName),
    passportSeries: toTrimmedString(source.passportSeries),
    passportNumber: toTrimmedString(source.passportNumber),
    passportIssuedBy: toTrimmedString(source.passportIssuedBy),
    passportIssuedDate: toTrimmedString(source.passportIssuedDate),
    passportDepartmentCode: toTrimmedString(source.passportDepartmentCode),
    registrationAddress: toTrimmedString(source.registrationAddress),
    residenceAddress: toTrimmedString(source.residenceAddress),
    phone: toTrimmedString(source.phone),
    email: toTrimmedString(source.email),
    bankName: toTrimmedString(source.bankName),
    cardNumber: toTrimmedString(source.cardNumber),
    sbpPhone: toTrimmedString(source.sbpPhone),
    bik: toTrimmedString(source.bik),
    checkingAccount: toTrimmedString(source.checkingAccount),
    correspondentAccount: toTrimmedString(source.correspondentAccount),
  };
};

const hasPrivateSellerRfValues = (value) => {
  const normalized = normalizePrivatePersonRfProfile(value);
  return Boolean(
    normalized.fullName ||
      normalized.passportSeries ||
      normalized.passportNumber ||
      normalized.passportIssuedBy ||
      normalized.passportIssuedDate ||
      normalized.passportDepartmentCode ||
      normalized.registrationAddress ||
      normalized.residenceAddress ||
      normalized.phone ||
      normalized.email ||
      normalized.bankName ||
      normalized.cardNumber ||
      normalized.sbpPhone ||
      normalized.bik ||
      normalized.checkingAccount ||
      normalized.correspondentAccount
  );
};

const toDisplayOrPlaceholder = (value, placeholder) => {
  const normalized = toTrimmedString(value);
  return normalized || placeholder;
};

const toEmailDisplayOrNotice = (value) => {
  const normalized = toTrimmedString(value);
  return normalized || 'отсутствует (уведомления по телефону/мессенджеру)';
};

const buildSellerPersonPaymentDetailsDisplay = ({
  sbpPhone,
}) => {
  if (sbpPhone) {
    return `по номеру телефона ${sbpPhone}`;
  }
  return 'по согласованию Сторон';
};

const toRuDisplayDate = (value) => {
  const normalized = toTrimmedString(value);
  if (!normalized) {
    return '';
  }

  const isoMatch = normalized.match(/^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/);
  if (isoMatch) {
    return `${isoMatch[3]}.${isoMatch[2]}.${isoMatch[1]}`;
  }

  return normalized;
};

const buildPassportDisplay = (profile) => {
  const series = toTrimmedString(profile?.passportSeries);
  const number = toTrimmedString(profile?.passportNumber);
  if (series && number) {
    return `${series} ${number}`;
  }
  return series || number;
};

const buildPassportIssuedDisplay = (profile) => {
  const issuedBy = toTrimmedString(profile?.passportIssuedBy);
  const issuedDate = toRuDisplayDate(profile?.passportIssuedDate);
  const departmentCode = toTrimmedString(profile?.passportDepartmentCode);
  const base = [issuedBy, issuedDate ? `дата: ${issuedDate}` : ''].filter(Boolean).join(', ');
  const withCode = [base, departmentCode ? `код подразделения: ${departmentCode}` : ''].filter(Boolean).join(', ');
  return withCode;
};

const supplierPersonProfileToPrivateSellerRf = (supplierProfile) => {
  const source = supplierProfile && typeof supplierProfile === 'object' ? supplierProfile : {};
  const primaryBankAccount = getPrimaryBankAccount(source.bankAccounts, source);
  return normalizePrivatePersonRfProfile({
    fullName: source.companyName,
    passportSeries: source.passportSeries,
    passportNumber: source.passportNumber,
    passportIssuedBy: source.passportIssuedBy,
    passportIssuedDate: source.passportIssuedDate,
    passportDepartmentCode: source.passportDepartmentCode,
    registrationAddress: source.registrationAddress || source.legalAddress,
    residenceAddress: source.residenceAddress,
    phone: source.phone,
    email: source.email,
    bankName: primaryBankAccount.bankName || source.bankName,
    cardNumber: primaryBankAccount.cardNumber || source.cardNumber,
    sbpPhone: primaryBankAccount.sbpPhone || source.sbpPhone || source.phone,
    bik: primaryBankAccount.bik || source.bik,
    checkingAccount: primaryBankAccount.checkingAccount || source.checkingAccount,
    correspondentAccount: primaryBankAccount.correspondentAccount || source.correspondentAccount,
  });
};

const buildPrivateBuyerProfileFromCounterparty = (counterparty) =>
  normalizePrivatePersonRfProfile({
    fullName: counterparty?.name,
    passportSeries: counterparty?.passportSeries,
    passportNumber: counterparty?.passportNumber,
    passportIssuedBy: counterparty?.passportIssuedBy,
    passportIssuedDate: counterparty?.passportIssuedDate,
    passportDepartmentCode: counterparty?.passportDepartmentCode,
    registrationAddress: counterparty?.registrationAddress,
    residenceAddress: counterparty?.residenceAddress,
    phone: counterparty?.phone,
    email: counterparty?.email,
  });

const normalizePersonIdentity = (value) => toTrimmedString(value).replace(/\s+/g, ' ').toLowerCase();

const reconcilePrivateBuyerRfWithCounterparty = ({ privateBuyerRf, counterparty }) => {
  if (toCounterpartyType(counterparty?.legalType, counterparty?.name) !== 'person') {
    return privateBuyerRf;
  }

  const counterpartyBuyerRf = buildPrivateBuyerProfileFromCounterparty(counterparty);
  const hasCounterpartyPassport = Boolean(counterpartyBuyerRf.passportSeries && counterpartyBuyerRf.passportNumber);
  const hasPrivateBuyerPassport = Boolean(privateBuyerRf.passportSeries && privateBuyerRf.passportNumber);
  const isSamePersonByPassport =
    hasCounterpartyPassport &&
    hasPrivateBuyerPassport &&
    counterpartyBuyerRf.passportSeries === privateBuyerRf.passportSeries &&
    counterpartyBuyerRf.passportNumber === privateBuyerRf.passportNumber;

  const counterpartyNameIdentity = normalizePersonIdentity(counterpartyBuyerRf.fullName);
  const privateBuyerNameIdentity = normalizePersonIdentity(privateBuyerRf.fullName);
  const isSamePersonByName = Boolean(
    counterpartyNameIdentity &&
      privateBuyerNameIdentity &&
      counterpartyNameIdentity === privateBuyerNameIdentity
  );

  if (!isSamePersonByPassport && !isSamePersonByName) {
    return privateBuyerRf;
  }

  // When contract buyer matches the selected physical counterparty,
  // use counterparty passport fields as the source of truth
  // so stale values from previous buyers are not carried over.
  return normalizePrivatePersonRfProfile({
    ...privateBuyerRf,
    fullName: counterpartyBuyerRf.fullName || privateBuyerRf.fullName,
    passportSeries: counterpartyBuyerRf.passportSeries || privateBuyerRf.passportSeries,
    passportNumber: counterpartyBuyerRf.passportNumber || privateBuyerRf.passportNumber,
    passportIssuedBy: counterpartyBuyerRf.passportIssuedBy,
    passportIssuedDate: counterpartyBuyerRf.passportIssuedDate,
    passportDepartmentCode: counterpartyBuyerRf.passportDepartmentCode,
    registrationAddress: counterpartyBuyerRf.registrationAddress || privateBuyerRf.registrationAddress,
    residenceAddress: counterpartyBuyerRf.residenceAddress || privateBuyerRf.residenceAddress,
    phone: counterpartyBuyerRf.phone || privateBuyerRf.phone,
    email: counterpartyBuyerRf.email || privateBuyerRf.email,
  });
};

const buildContractTemplateContext = ({ contract, counterparty, invoice, settings }) => {
  const supplierProfile = resolveSupplierProfileFromSettings(settings, invoice?.supplierProfileId || contract?.supplierProfileId);
  const createdDate = isNonEmptyString(contract?.createdAt) ? contract.createdAt : formatDate();
  const createdDateObject = parseRuDateToDate(createdDate);
  const contractData = contract?.contractData && typeof contract.contractData === 'object' ? contract.contractData : {};
  const buyerType = toCounterpartyType(counterparty?.legalType, counterparty?.name);
  const supplierType = toCounterpartyType(supplierProfile?.legalType, supplierProfile?.companyName);
  const supplierRegistrationLabel = supplierType === 'ip' ? 'ОГРНИП' : 'ОГРН';
  const supplierRegistrationNumber =
    supplierType === 'ip' ? toTrimmedString(supplierProfile?.ogrnip) : toTrimmedString(supplierProfile?.ogrn);
  const buyerRegistrationLabel = buyerType === 'ip' ? 'ОГРНИП' : 'ОГРН';
  const buyerRegistrationNumber =
    buyerType === 'ip' ? toTrimmedString(counterparty?.ogrnip) : toTrimmedString(counterparty?.ogrn);
  const supplierAddress = toTrimmedString(supplierProfile?.legalAddress);
  const supplierPrimaryBankAccount =
    toSupplierBankAccount(invoice?.supplierBankAccount) || getPrimaryBankAccount(supplierProfile?.bankAccounts, supplierProfile);
  const buyerPrimaryBankAccount = getPrimaryBankAccount(counterparty?.bankAccounts, counterparty);
  const contractItemsSource = Array.isArray(invoice?.items)
    ? invoice.items
    : Array.isArray(contractData.contractItems)
      ? contractData.contractItems
      : Array.isArray(contractData.items)
        ? contractData.items
        : [];
  const invoiceMarkupPercent = invoice ? toMarkupPercent(invoice.commissionPercent) : null;
  const fallbackMarkupPercent =
    invoiceMarkupPercent == null && contract?.invoiceId ? toMarkupPercent(contract?.markupPercent) : 0;
  const templateMarkupPercent = invoiceMarkupPercent == null ? fallbackMarkupPercent : invoiceMarkupPercent;
  const templateMarkupFactor = 1 + templateMarkupPercent / 100;
  const roundMoneyValue = (value) => Math.round(toNonNegativeNumber(value, 0) * 100) / 100;
  const items = normalizeInvoiceItems(contractItemsSource).map((item, index) => {
    const quantity = toNonNegativeNumber(item.quantity, 0);
    const unitPrice = toNonNegativeNumber(item.price, 0);
    const unitPriceWithMarkup = roundMoneyValue(unitPrice * templateMarkupFactor);
    const lineTotal = roundMoneyValue(quantity * unitPriceWithMarkup);

    return {
      index: index + 1,
      name: toTrimmedString(item.description),
      qty: quantity,
      unit: toTrimmedString(item.unit) || 'шт',
      price: formatMoney(unitPriceWithMarkup),
      line_total: formatMoney(lineTotal),
      lineTotalRaw: lineTotal,
    };
  });

  const totalAmountRaw =
    contract?.amount == null
      ? invoice
        ? toNonNegativeNumber(invoice.amount, 0)
        : items.reduce((sum, item) => sum + toNonNegativeNumber(item.lineTotalRaw, 0), 0)
      : toNonNegativeNumber(contract.amount, 0);
  const deliveryDate = toTrimmedString(contract?.deliveryDate);
  const legacyPrivateSellerRf = normalizePrivatePersonRfProfile(settings?.privateSellerRf);
  const supplierPersonPrivateSellerRf =
    supplierType === 'person' ? supplierPersonProfileToPrivateSellerRf(supplierProfile) : null;
  const privateSellerRf = normalizePrivatePersonRfProfile({
    ...legacyPrivateSellerRf,
    ...(supplierPersonPrivateSellerRf || {}),
  });
  const privateBuyerRf = reconcilePrivateBuyerRfWithCounterparty({
    privateBuyerRf: normalizePrivatePersonRfProfile(contractData.privateBuyerRf),
    counterparty,
  });
  const hasPrepayment = Object.prototype.hasOwnProperty.call(contractData, 'hasPrepayment')
    ? Boolean(contractData.hasPrepayment)
    : true;
  const prepaymentPercent = Math.min(100, toNonNegativeNumber(contractData.prepaymentPercent, 100));
  const penaltyPercentPerDay = toNonNegativeNumber(contractData.penaltyPercentPerDay, 0);
  const monthName = createdDateObject.toLocaleString('ru-RU', { month: 'long', day: 'numeric' }).replace(/^\d+\s+/u, '');
  const readableDate = `«${createdDateObject.getDate()}» ${monthName} ${createdDateObject.getFullYear()} года`;
  const privateSellerAddress = toTrimmedString(privateSellerRf.registrationAddress || privateSellerRf.residenceAddress);
  const privateBuyerAddress = toTrimmedString(privateBuyerRf.registrationAddress || privateBuyerRf.residenceAddress);
  const privateSellerPassportDisplay = buildPassportDisplay(privateSellerRf);
  const privateBuyerPassportDisplay = buildPassportDisplay(privateBuyerRf);
  const privateSellerPassportIssuedDisplay = buildPassportIssuedDisplay(privateSellerRf);
  const privateBuyerPassportIssuedDisplay = buildPassportIssuedDisplay(privateBuyerRf);
  const sellerPersonPassportClause = privateSellerPassportDisplay ? `, паспорт: ${privateSellerPassportDisplay}` : '';
  const sellerPersonPassportIssuedClause = privateSellerPassportIssuedDisplay
    ? `, выдан ${privateSellerPassportIssuedDisplay}`
    : '';
  const buyerPersonPassportClause = privateBuyerPassportDisplay ? `, паспорт: ${privateBuyerPassportDisplay}` : '';
  const buyerPersonPassportIssuedClause = privateBuyerPassportIssuedDisplay
    ? `, выдан ${privateBuyerPassportIssuedDisplay}`
    : '';
  const privateSellerBankName = toTrimmedString(privateSellerRf.bankName) || supplierPrimaryBankAccount.bankName;
  const privateSellerCardNumber = toTrimmedString(privateSellerRf.cardNumber) || toTrimmedString(supplierPrimaryBankAccount.cardNumber);
  const privateSellerSbpPhone =
    toTrimmedString(privateSellerRf.sbpPhone) ||
    toTrimmedString(supplierPrimaryBankAccount.sbpPhone) ||
    toTrimmedString(privateSellerRf.phone);
  const privateSellerBik = toTrimmedString(privateSellerRf.bik) || supplierPrimaryBankAccount.bik;
  const privateSellerCheckingAccount =
    toTrimmedString(privateSellerRf.checkingAccount) || supplierPrimaryBankAccount.checkingAccount;
  const privateSellerCorrespondentAccount =
    toTrimmedString(privateSellerRf.correspondentAccount) || supplierPrimaryBankAccount.correspondentAccount;
  const preferredSellerAddressForIp = toTrimmedString(supplierAddress || privateSellerAddress);
  const preferredSellerAddressForPerson = toTrimmedString(privateSellerAddress || supplierAddress);
  const sellerAddressForTemplate = supplierType === 'ip' ? preferredSellerAddressForIp : preferredSellerAddressForPerson;
  const amountWords = amountToRublesWords(totalAmountRaw);
  const defaultCity = extractCityFromAddress(sellerAddressForTemplate);
  const contractSigningCity = toTrimmedString(contractData.signingCity) || defaultCity;
  const deliveryCity = toTrimmedString(contractData.deliveryCity);
  const deliveryCityDisplay = deliveryCity || contractSigningCity || defaultCity || '[город доставки]';
  const deliveryTermDays = toPositiveInteger(contractData.deliveryTermDays, 35);
  const deliveryTermBasis =
    toTrimmedString(contractData.deliveryTermBasis) || 'с даты поступления полной оплаты';
  const deliveryCostPayer = toTrimmedString(contractData.deliveryCostPayer);
  const deliveryCostPayerLabel =
    deliveryCostPayer === 'seller'
      ? 'за счет Продавца (включена в цену)'
      : deliveryCostPayer === 'buyer'
        ? 'за счет Покупателя (оплачивается отдельно по тарифам ТК)'
        : '[выбрать]';
  const deliveryCostPayerSupplierLabel =
    deliveryCostPayer === 'seller'
      ? 'за счет Поставщика (включена в цену)'
      : deliveryCostPayer === 'buyer'
        ? 'за счет Покупателя (оплачивается отдельно по тарифам ТК)'
        : '[выбрать]';
  const deliveryMethodLabel = toTrimmedString(contractData.deliveryMethod) || 'ТК/курьер по согласованию Сторон';
  const supplierTaxBasis = toTrimmedString(contractData.supplierTaxBasis);
  const purchasePurpose = toTrimmedString(contractData.purchasePurpose) === 'business' ? 'business' : 'personal';
  const purchasePurposeLabel =
    purchasePurpose === 'business' ? 'для предпринимательской деятельности' : 'для личных нужд';
  const rawConfPenaltyValue = contractData.confidentialityPenaltyAmount;
  const hasConfPenaltyValue =
    rawConfPenaltyValue !== null && rawConfPenaltyValue !== undefined && String(rawConfPenaltyValue).trim() !== '';
  const confidentialityPenaltyAmount = hasConfPenaltyValue ? toNonNegativeNumber(rawConfPenaltyValue, 0) : null;
  const confidentialityPenaltyAmountFormatted =
    confidentialityPenaltyAmount == null ? '[например: 30 000 руб.]' : formatMoney(confidentialityPenaltyAmount);
  const goodsSaleVatClauseText = buildGoodsSaleVatClauseText({
    totalAmountRaw,
    vatRate: contract?.vatRate,
    vatMode: contract?.vatMode,
    supplierTaxBasis,
    supplierType,
  });
  const supplierInnValue = toTrimmedString(supplierProfile?.inn);
  const supplierOgrnipValue = toTrimmedString(supplierProfile?.ogrnip);
  const supplierDisplayAddress = sellerAddressForTemplate;
  const sellerIpName = stripIpPrefix(supplierProfile?.companyName) || toTrimmedString(supplierProfile?.companyName);
  const sellerIpFullIntro = sellerIpName
    ? `Индивидуальный предприниматель ${sellerIpName}`
    : 'Индивидуальный предприниматель';
  const sellerPersonHasBankAccountRequisites = Boolean(
    privateSellerBankName && privateSellerCheckingAccount && privateSellerBik && privateSellerCorrespondentAccount
  );
  const sellerPersonHasCardNumber = Boolean(privateSellerCardNumber);
  const sellerPersonHasSbpPhone = Boolean(privateSellerSbpPhone);
  const sellerPersonPaymentDetailsDisplay = buildSellerPersonPaymentDetailsDisplay({
    bankName: privateSellerBankName,
    checkingAccount: privateSellerCheckingAccount,
    bik: privateSellerBik,
    correspondentAccount: privateSellerCorrespondentAccount,
    cardNumber: privateSellerCardNumber,
    sbpPhone: privateSellerSbpPhone,
  });
  const supplierSignerPosition =
    pickContractDataString(contractData, 'supplier_signer_position', 'supplierSignerPosition') ||
    (supplierType === 'ip' ? 'индивидуальный предприниматель' : 'директор');
  const supplierSignerName =
    pickContractDataString(contractData, 'supplier_signer_name', 'supplierSignerName') ||
    (supplierType === 'ip'
      ? sellerIpName || toTrimmedString(supplierProfile?.companyName) || '[ФИО ИП]'
      : toTrimmedString(supplierProfile?.directorName) || toTrimmedString(supplierProfile?.directorGenitive) || '[ФИО подписанта]');
  const supplierSignerBasis =
    pickContractDataString(contractData, 'supplier_signer_basis', 'supplierSignerBasis') ||
    (supplierType === 'ip' ? 'свидетельства о государственной регистрации в качестве ИП' : 'Устава');
  const buyerSignerPosition =
    pickContractDataString(contractData, 'buyer_signer_position', 'buyerSignerPosition') ||
    (buyerType === 'ip' ? 'индивидуальный предприниматель' : 'директор');
  const buyerSignerName =
    pickContractDataString(contractData, 'buyer_signer_name', 'buyerSignerName') ||
    toTrimmedString(counterparty?.directorName || counterparty?.contactPerson || counterparty?.name) ||
    '[ФИО подписанта]';
  const buyerSignerBasis =
    pickContractDataString(contractData, 'buyer_signer_basis', 'buyerSignerBasis') ||
    (buyerType === 'ip' ? 'свидетельства о государственной регистрации в качестве ИП' : 'Устава');
  const prepaymentAmountRaw = (totalAmountRaw * prepaymentPercent) / 100;
  const finalPaymentPercent = Math.max(0, 100 - prepaymentPercent);
  const finalPaymentAmountRaw = Math.max(0, totalAmountRaw - prepaymentAmountRaw);
  const paymentDueDateDisplay =
    toTrimmedString(invoice?.paymentDueDate) ||
    pickContractDataString(contractData, 'payment_due_date', 'paymentDueDate') ||
    '[дата из счета/спецификации]';
  const customPaymentTermsDisplay =
    pickContractDataString(contractData, 'custom_payment_terms', 'customPaymentTerms') ||
    'по согласованию Сторон';
  const paymentOption100Mark = hasPrepayment && prepaymentPercent >= 100 ? 'X' : ' ';
  const paymentOptionPartialMark = hasPrepayment && prepaymentPercent > 0 && prepaymentPercent < 100 ? 'X' : ' ';
  const paymentOptionCustomMark = !hasPrepayment || prepaymentPercent <= 0 ? 'X' : ' ';
  const selectedPaymentTermsClause =
    paymentOption100Mark === 'X'
      ? '100% предоплата.'
      : paymentOptionPartialMark === 'X'
        ? `Предоплата ${prepaymentPercent}% (${formatMoney(prepaymentAmountRaw)}) и окончательный расчет ${finalPaymentPercent}% (${formatMoney(finalPaymentAmountRaw)}) до ${paymentDueDateDisplay}.`
        : `Иное условие оплаты: ${customPaymentTermsDisplay}.`;
  const selectedPaymentTermsSpecClause =
    paymentOption100Mark === 'X'
      ? '100% предоплата'
      : paymentOptionPartialMark === 'X'
        ? `предоплата ${prepaymentPercent}% (${formatMoney(prepaymentAmountRaw)}) + доплата ${finalPaymentPercent}% (${formatMoney(finalPaymentAmountRaw)}) до ${paymentDueDateDisplay}`
        : `иное условие: ${customPaymentTermsDisplay}`;

  return {
    contract_id: contract?.id,
    contract_number: toTrimmedString(contract?.number),
    contract_title: toTrimmedString(contract?.title),
    contract_type: toTrimmedString(contract?.type),
    created_date: createdDate,
    created_date_long: readableDate,
    city: defaultCity,
    contract_signing_city: contractSigningCity,
    payment_terms: toPositiveInteger(contract?.paymentTerms, 10),
    has_delivery: Boolean(contract?.includeDelivery && deliveryDate),
    delivery_date: deliveryDate || 'по дополнительному согласованию',
    delivery_city_display: deliveryCityDisplay,
    delivery_term_days: deliveryTermDays,
    delivery_term_basis: deliveryTermBasis,
    delivery_cost_payer_label: deliveryCostPayerLabel,
    delivery_cost_payer_supplier_label: deliveryCostPayerSupplierLabel,
    delivery_method_label: deliveryMethodLabel,
    purchase_purpose: purchasePurpose,
    purchase_purpose_label: purchasePurposeLabel,
    buyer_purchase_for_personal_needs: purchasePurpose === 'personal',
    has_prepayment: hasPrepayment && prepaymentPercent > 0,
    prepayment_percent: prepaymentPercent,
    prepayment_amount_formatted: formatMoney(prepaymentAmountRaw),
    final_payment_percent: finalPaymentPercent,
    final_payment_amount_formatted: formatMoney(finalPaymentAmountRaw),
    payment_due_date_display: paymentDueDateDisplay,
    payment_option_100_mark: paymentOption100Mark,
    payment_option_partial_mark: paymentOptionPartialMark,
    payment_option_custom_mark: paymentOptionCustomMark,
    custom_payment_terms_display: customPaymentTermsDisplay,
    selected_payment_terms_clause: selectedPaymentTermsClause,
    selected_payment_terms_spec_clause: selectedPaymentTermsSpecClause,
    has_penalty: penaltyPercentPerDay > 0,
    penalty_percent_per_day: penaltyPercentPerDay,
    vat_rate: toVatRate(contract?.vatRate),
    vat_mode: toVatMode(contract?.vatMode),
    goods_sale_vat_clause_text: goodsSaleVatClauseText,
    markup_percent: toMarkupPercent(contract?.markupPercent),
    markup_mode: toMarkupMode(contract?.markupMode),
    markup_calc_mode: toMarkupCalcMode(contract?.markupCalcMode),
    total_amount_raw: totalAmountRaw,
    total_amount_formatted: formatMoney(totalAmountRaw),
    total_amount_words: amountWords.words,
    total_amount_words_full: amountWords.full,
    confidentiality_penalty_amount: confidentialityPenaltyAmount == null ? '' : confidentialityPenaltyAmount,
    confidentiality_penalty_amount_formatted: confidentialityPenaltyAmountFormatted,
    supplier_name: toTrimmedString(supplierProfile?.companyName),
    supplier_legal_type: supplierType,
    supplier_is_ip: supplierType === 'ip',
    supplier_is_company: supplierType === 'ooo' || supplierType === 'ao',
    supplier_is_person: supplierType === 'person',
    supplier_inn: supplierInnValue,
    supplier_kpp: supplierType === 'ooo' ? toTrimmedString(supplierProfile?.kpp) : '',
    supplier_has_kpp: supplierType === 'ooo' && isNonEmptyString(supplierProfile?.kpp),
    supplier_ogrn: supplierRegistrationNumber,
    supplier_ogrnip: supplierOgrnipValue,
    supplier_registration_label: supplierRegistrationLabel,
    supplier_registration_number: supplierRegistrationNumber,
    supplier_director_genitive: toTrimmedString(supplierProfile?.directorGenitive),
    supplier_address: supplierAddress,
    supplier_address_display: toDisplayOrPlaceholder(supplierDisplayAddress || supplierAddress, '[адрес продавца]'),
    supplier_email: toTrimmedString(supplierProfile?.email),
    supplier_email_display: toEmailDisplayOrNotice(supplierProfile?.email),
    supplier_phone: toTrimmedString(supplierProfile?.phone),
    supplier_phone_display: toDisplayOrPlaceholder(supplierProfile?.phone, '[____]'),
    supplier_bank_name: supplierPrimaryBankAccount.bankName,
    supplier_bank_name_display: toDisplayOrPlaceholder(supplierPrimaryBankAccount.bankName, '[банк]'),
    supplier_bik: supplierPrimaryBankAccount.bik,
    supplier_bik_display: toDisplayOrPlaceholder(supplierPrimaryBankAccount.bik, '[____]'),
    supplier_correspondent_account: supplierPrimaryBankAccount.correspondentAccount,
    supplier_correspondent_account_display: toDisplayOrPlaceholder(supplierPrimaryBankAccount.correspondentAccount, '[____]'),
    supplier_checking_account: supplierPrimaryBankAccount.checkingAccount,
    supplier_checking_account_display: toDisplayOrPlaceholder(supplierPrimaryBankAccount.checkingAccount, '[____]'),
    supplier_signer_position: supplierSignerPosition,
    supplier_signer_name: supplierSignerName,
    supplier_signer_basis: supplierSignerBasis,
    seller_ip_name: sellerIpName || '[ФИО ИП]',
    seller_ip_full_intro: sellerIpFullIntro,
    seller_ip_inn_display: toDisplayOrPlaceholder(supplierInnValue, '[____]'),
    seller_ip_ogrnip_display: toDisplayOrPlaceholder(supplierOgrnipValue, '[____]'),
    buyer_name: getCounterpartyFormalName(counterparty),
    buyer_legal_type: buyerType,
    buyer_is_ip: buyerType === 'ip',
    buyer_is_company: buyerType === 'ooo' || buyerType === 'ao',
    buyer_contact_person: toTrimmedString(counterparty?.contactPerson),
    buyer_director_name: toTrimmedString(counterparty?.directorName || counterparty?.contactPerson),
    buyer_inn: toTrimmedString(counterparty?.inn),
    buyer_kpp: toTrimmedString(counterparty?.kpp),
    buyer_has_kpp: isNonEmptyString(counterparty?.kpp),
    buyer_registration_label: buyerRegistrationLabel,
    buyer_registration_number: buyerRegistrationNumber,
    buyer_ogrn: toTrimmedString(counterparty?.ogrn),
    buyer_ogrnip: toTrimmedString(counterparty?.ogrnip),
    buyer_signer_position: buyerSignerPosition,
    buyer_signer_name: buyerSignerName,
    buyer_signer_basis: buyerSignerBasis,
    buyer_address: toTrimmedString(counterparty?.address),
    buyer_email: toTrimmedString(counterparty?.email),
    buyer_email_display: toEmailDisplayOrNotice(counterparty?.email),
    buyer_phone: toTrimmedString(counterparty?.phone),
    buyer_phone_display: toDisplayOrPlaceholder(counterparty?.phone, '[____]'),
    buyer_bank_name: buyerPrimaryBankAccount.bankName,
    buyer_bik: buyerPrimaryBankAccount.bik,
    buyer_correspondent_account: buyerPrimaryBankAccount.correspondentAccount,
    buyer_checking_account: buyerPrimaryBankAccount.checkingAccount,
    invoice_number: toTrimmedString(invoice?.number),
    invoice_date: toTrimmedString(invoice?.date),
    privateSellerRf,
    privateBuyerRf,
    seller_person_full_name: privateSellerRf.fullName,
    seller_person_full_name_display: toDisplayOrPlaceholder(privateSellerRf.fullName, '[ФИО Продавца]'),
    seller_person_passport_series: privateSellerRf.passportSeries,
    seller_person_passport_number: privateSellerRf.passportNumber,
    seller_person_passport_display: privateSellerPassportDisplay,
    seller_person_passport_clause: sellerPersonPassportClause,
    seller_person_has_passport: Boolean(privateSellerPassportDisplay),
    seller_person_passport_issued_by: privateSellerRf.passportIssuedBy,
    seller_person_passport_issued_date: privateSellerRf.passportIssuedDate,
    seller_person_passport_department_code: privateSellerRf.passportDepartmentCode,
    seller_person_passport_issued_display: privateSellerPassportIssuedDisplay,
    seller_person_passport_issued_clause: sellerPersonPassportIssuedClause,
    seller_person_has_passport_issued: Boolean(privateSellerPassportIssuedDisplay),
    seller_person_passport_line_visible: supplierType === 'person' && Boolean(privateSellerPassportDisplay),
    seller_person_passport_issued_line_visible: supplierType === 'person' && Boolean(privateSellerPassportIssuedDisplay),
    seller_person_registration_address: privateSellerRf.registrationAddress,
    seller_person_residence_address: privateSellerRf.residenceAddress,
    seller_person_address_display: toDisplayOrPlaceholder(privateSellerAddress, '[адрес продавца]'),
    seller_person_phone: privateSellerRf.phone,
    seller_person_phone_display: toDisplayOrPlaceholder(privateSellerRf.phone, '[____]'),
    seller_person_email: privateSellerRf.email,
    seller_person_email_display: toEmailDisplayOrNotice(privateSellerRf.email),
    seller_person_bank_name: privateSellerBankName,
    seller_person_card_number: privateSellerCardNumber,
    seller_person_sbp_phone: privateSellerSbpPhone,
    seller_person_bik: privateSellerBik,
    seller_person_checking_account: privateSellerCheckingAccount,
    seller_person_correspondent_account: privateSellerCorrespondentAccount,
    seller_person_bank_name_display: toDisplayOrPlaceholder(privateSellerBankName, '[банк]'),
    seller_person_card_number_display: toDisplayOrPlaceholder(privateSellerCardNumber, '[номер карты]'),
    seller_person_sbp_phone_display: toDisplayOrPlaceholder(privateSellerSbpPhone, '[номер для СБП]'),
    seller_person_bik_display: toDisplayOrPlaceholder(privateSellerBik, '[____]'),
    seller_person_checking_account_display: toDisplayOrPlaceholder(privateSellerCheckingAccount, '[____]'),
    seller_person_correspondent_account_display: toDisplayOrPlaceholder(privateSellerCorrespondentAccount, '[____]'),
    seller_person_payment_details_display: sellerPersonPaymentDetailsDisplay,
    seller_person_has_card_number: sellerPersonHasCardNumber,
    seller_person_has_sbp_phone: sellerPersonHasSbpPhone,
    seller_person_has_bank_account_requisites: sellerPersonHasBankAccountRequisites,
    seller_person_email_missing: !privateSellerRf.email,
    buyer_person_full_name: privateBuyerRf.fullName,
    buyer_person_full_name_display: toDisplayOrPlaceholder(privateBuyerRf.fullName, '[ФИО Покупателя]'),
    buyer_person_passport_series: privateBuyerRf.passportSeries,
    buyer_person_passport_number: privateBuyerRf.passportNumber,
    buyer_person_passport_display: privateBuyerPassportDisplay,
    buyer_person_passport_clause: buyerPersonPassportClause,
    buyer_person_has_passport: Boolean(privateBuyerPassportDisplay),
    buyer_person_passport_issued_by: privateBuyerRf.passportIssuedBy,
    buyer_person_passport_issued_date: privateBuyerRf.passportIssuedDate,
    buyer_person_passport_department_code: privateBuyerRf.passportDepartmentCode,
    buyer_person_passport_issued_display: privateBuyerPassportIssuedDisplay,
    buyer_person_passport_issued_clause: buyerPersonPassportIssuedClause,
    buyer_person_has_passport_issued: Boolean(privateBuyerPassportIssuedDisplay),
    buyer_person_registration_address: privateBuyerRf.registrationAddress,
    buyer_person_residence_address: privateBuyerRf.residenceAddress,
    buyer_person_address_display: toDisplayOrPlaceholder(privateBuyerAddress, '[____]'),
    buyer_person_phone: privateBuyerRf.phone,
    buyer_person_phone_display: toDisplayOrPlaceholder(privateBuyerRf.phone, '[____]'),
    buyer_person_email: privateBuyerRf.email,
    buyer_person_email_display: toEmailDisplayOrNotice(privateBuyerRf.email),
    buyer_person_email_missing: !privateBuyerRf.email,
    has_items: items.length > 0,
    items,
  };
};

const nextContractNumber = (contracts) => {
  const currentYear = new Date().getFullYear();
  const matcher = new RegExp(`^Д-${currentYear}-(\\d+)$`);
  const maxValue = contracts.reduce((max, contract) => {
    const match = matcher.exec(String(contract.number || ''));
    if (!match) {
      return max;
    }

    const value = Number(match[1]);
    return Number.isFinite(value) ? Math.max(max, value) : max;
  }, 0);

  return `Д-${currentYear}-${String(maxValue + 1).padStart(3, '0')}`;
};

const nextInvoiceNumber = (invoices) => {
  const currentYear = new Date().getFullYear();
  const matcher = new RegExp(`^СЧ-${currentYear}-(\\d+)$`);
  const maxValue = invoices.reduce((max, invoice) => {
    const match = matcher.exec(String(invoice.number || ''));
    if (!match) {
      return max;
    }

    const value = Number(match[1]);
    return Number.isFinite(value) ? Math.max(max, value) : max;
  }, 0);

  return `СЧ-${currentYear}-${String(maxValue + 1).padStart(3, '0')}`;
};

const buildDashboardStats = (contracts, invoices) => {
  const totalContracts = contracts.length;
  const pendingContracts = contracts.filter((contract) => contract.status === CONTRACT_STATUS.PENDING_APPROVAL).length;
  const paidInvoicesAmount = invoices
    .filter((invoice) => invoice.status === 'Оплачен')
    .reduce((sum, invoice) => sum + Number(invoice.amount || 0), 0);

  return {
    totalContracts,
    pendingContracts,
    paidInvoicesAmount,
  };
};

const fullHtmlDocument = (html, css = '') => `
  <!doctype html>
  <html>
    <head>
      <meta charset="utf-8" />
      <style>
        ${css}
        html, body {
          margin: 0;
          padding: 0;
          -webkit-print-color-adjust: exact;
        }
        .preview-root { padding: 0; }
        .document-page {
          box-shadow: none;
          margin: 0 !important;
          width: auto !important;
          min-height: auto !important;
          padding: 0 !important;
          box-sizing: border-box !important;
        }
      </style>
    </head>
    <body>
      <div class="preview-root">${html}</div>
    </body>
  </html>
`;

// html-to-docx fails on percentage width values in table-related styles
// and throws: "Invalid XML name: @w". Strip those declarations for DOCX export.
const DOCX_UNSUPPORTED_PERCENT_WIDTH_REGEX = /(?<![-\w])width\s*:\s*[^;{}"]*%(?:\s*!important)?\s*;?/gi;

const sanitizeDocxStyles = (value) => {
  if (!isNonEmptyString(value)) {
    return '';
  }

  return value.replace(DOCX_UNSUPPORTED_PERCENT_WIDTH_REGEX, '');
};

const parseJsonSafe = (value, fallback) => {
  if (!isNonEmptyString(value)) {
    return fallback;
  }

  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};

const stringifyJsonSafe = (value, fallback) => {
  try {
    return JSON.stringify(value ?? fallback);
  } catch {
    return JSON.stringify(fallback);
  }
};

const getDb = () => {
  if (!db) {
    throw new ApiError(500, 'База данных не инициализирована.');
  }

  return db;
};

const mapInvoiceRow = (row) => {
  const parsedItems = parseJsonSafe(row.items_json, []);
  const parsedSupplierBankAccount = parseJsonSafe(row.supplier_bank_account_json, null);
  const supplierBankAccount = toSupplierBankAccount(parsedSupplierBankAccount);
  return {
    id: row.id,
    number: row.number,
    date: row.date,
    paymentDueDate: isNonEmptyString(row.payment_due_date) ? row.payment_due_date : undefined,
    amount: Number(row.amount || 0),
    currency: toCurrency(row.currency),
    status: toInvoiceStatus(row.status),
    commissionPercent: toMarkupPercent(row.commission_percent),
    vatRate: toVatRate(row.vat_rate),
    vatMode: toVatMode(row.vat_mode),
    supplierProfileId: isNonEmptyString(row.supplier_profile_id) ? row.supplier_profile_id : undefined,
    supplierBankAccount,
    counterpartyId: isNonEmptyString(row.counterparty_id) ? row.counterparty_id : undefined,
    items: Array.isArray(parsedItems) ? parsedItems : [],
  };
};

const mapContractRow = (row) => {
  const parsedCounterparty = parseJsonSafe(row.counterparty_json, {});
  const parsedContractData = parseJsonSafe(row.contract_data_json, {});
  const rawMarkupPercent = row.markup_percent == null ? NaN : Number(row.markup_percent);

  return {
    id: row.id,
    number: row.number,
    title: row.title,
    type: row.type,
    counterparty: parsedCounterparty && typeof parsedCounterparty === 'object' ? parsedCounterparty : {},
    status: row.status,
    createdAt: row.created_at,
    amount: row.amount == null ? undefined : Number(row.amount),
    supplierProfileId: isNonEmptyString(row.supplier_profile_id) ? row.supplier_profile_id : undefined,
    invoiceId: isNonEmptyString(row.invoice_id) ? row.invoice_id : undefined,
    paymentTerms: row.payment_terms == null ? undefined : Number(row.payment_terms),
    includeDelivery: Boolean(row.include_delivery),
    deliveryDate: row.delivery_date == null ? null : row.delivery_date,
    vatRate: toVatRate(row.vat_rate),
    vatMode: toVatMode(row.vat_mode),
    markupPercent: Number.isFinite(rawMarkupPercent) ? rawMarkupPercent : DEFAULT_CONTRACT_PRICING.markupPercent,
    markupMode: toMarkupMode(row.markup_mode),
    markupCalcMode: toMarkupCalcMode(row.markup_calc_mode),
    templateId: isNonEmptyString(row.template_id) ? row.template_id : undefined,
    templateName: isNonEmptyString(row.template_name) ? row.template_name : undefined,
    templateVersion: isNonEmptyString(row.template_version) ? row.template_version : undefined,
    contractData: parsedContractData && typeof parsedContractData === 'object' ? parsedContractData : {},
    htmlSnapshot: isNonEmptyString(row.html_snapshot) ? row.html_snapshot : undefined,
    snapshotCss: isNonEmptyString(row.snapshot_css) ? row.snapshot_css : undefined,
  };
};

const mapCounterpartyRow = (row) => {
  const bankAccounts = normalizeBankAccounts(parseJsonSafe(row.bank_accounts_json, []), {
    bankName: row.bank_name,
    checkingAccount: row.checking_account,
    correspondentAccount: row.correspondent_account,
    bik: row.bik,
  });
  const primaryBankAccount = getPrimaryBankAccount(bankAccounts);

  return {
    id: row.id,
    name: row.name,
    inn: row.inn,
    address: row.address,
    contactPerson: row.contact_person,
    email: row.email,
    phone: toTrimmedString(row.phone),
    legalType: toCounterpartyType(row.legal_type, row.name),
    directorName: toTrimmedString(row.director_name),
    ogrn: toTrimmedString(row.ogrn),
    kpp: toTrimmedString(row.kpp),
    ogrnip: toTrimmedString(row.ogrnip),
    passportSeries: toTrimmedString(row.passport_series),
    passportNumber: toTrimmedString(row.passport_number),
    passportIssuedBy: toTrimmedString(row.passport_issued_by),
    passportIssuedDate: toTrimmedString(row.passport_issued_date),
    passportDepartmentCode: toTrimmedString(row.passport_department_code),
    registrationAddress: toTrimmedString(row.registration_address),
    residenceAddress: toTrimmedString(row.residence_address),
    bankAccounts,
    bankName: primaryBankAccount.bankName,
    checkingAccount: primaryBankAccount.checkingAccount,
    correspondentAccount: primaryBankAccount.correspondentAccount,
    bik: primaryBankAccount.bik,
  };
};

const mapTemplateRow = (row) => ({
  id: row.id,
  name: row.name,
  type: row.type,
  version: row.version,
  updatedAt: row.updated_at,
  isActive: Boolean(row.is_active),
  content: normalizeTemplateContent(row.content_html),
  css: normalizeTemplateCss(row.css_text),
  variables: normalizeTemplateVariables(parseJsonSafe(row.variables_json, DEFAULT_TEMPLATE_VARIABLES)),
});

const getNextSortOrder = (tableName) => {
  const row = getDb().prepare(`SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort_order FROM ${tableName}`).get();
  return Number(row?.next_sort_order || 1);
};

const listCounterpartiesFromDb = () => {
  const rows = getDb()
    .prepare(
      `SELECT id, name, inn, address, contact_person, email, legal_type, director_name, ogrn, kpp, ogrnip, bank_name, checking_account, correspondent_account, bik, bank_accounts_json
       , phone, passport_series, passport_number, passport_issued_by, passport_issued_date, passport_department_code, registration_address, residence_address
       FROM counterparties
       ORDER BY sort_order DESC`
    )
    .all();

  return rows.map(mapCounterpartyRow);
};

const getCounterpartyByIdFromDb = (id) => {
  const row = getDb()
    .prepare(
      `SELECT id, name, inn, address, contact_person, email, legal_type, director_name, ogrn, kpp, ogrnip, bank_name, checking_account, correspondent_account, bik, bank_accounts_json
       , phone, passport_series, passport_number, passport_issued_by, passport_issued_date, passport_department_code, registration_address, residence_address
       FROM counterparties
       WHERE id = ?`
    )
    .get(id);

  return row ? mapCounterpartyRow(row) : null;
};

const getCounterpartyByInnFromDb = (inn) => {
  const normalizedInn = toTrimmedString(inn);
  if (!isNonEmptyString(normalizedInn)) {
    return null;
  }

  const row = getDb()
    .prepare(
      `SELECT id, name, inn, address, contact_person, email, legal_type, director_name, ogrn, kpp, ogrnip, bank_name, checking_account, correspondent_account, bik, bank_accounts_json
       , phone, passport_series, passport_number, passport_issued_by, passport_issued_date, passport_department_code, registration_address, residence_address
       FROM counterparties
       WHERE inn = ?
       ORDER BY sort_order DESC
       LIMIT 1`
    )
    .get(normalizedInn);

  return row ? mapCounterpartyRow(row) : null;
};

const listTemplatesFromDb = () => {
  const rows = getDb()
    .prepare(
      `SELECT id, name, type, version, updated_at, is_active, content_html, css_text, variables_json
       FROM templates
       ORDER BY sort_order DESC`
    )
    .all();

  return rows.map(mapTemplateRow);
};

const getTemplateByIdFromDb = (id) => {
  const row = getDb()
    .prepare(
      `SELECT id, name, type, version, updated_at, is_active, content_html, css_text, variables_json
       FROM templates
       WHERE id = ?`
    )
    .get(id);

  return row ? mapTemplateRow(row) : null;
};

const getTemplateForContract = ({ templateId, type }) => {
  if (isNonEmptyString(templateId)) {
    const byId = getTemplateByIdFromDb(templateId.trim());
    if (!byId) {
      throw new ApiError(404, 'Шаблон не найден.');
    }
    if (!byId.isActive) {
      throw new ApiError(400, 'Выбранный шаблон отключен.');
    }
    return byId;
  }

  const templates = listTemplatesFromDb();
  const byType = templates.find((template) => template.isActive && template.type === type);
  if (byType) {
    return byType;
  }

  const firstActive = templates.find((template) => template.isActive);
  if (firstActive) {
    return firstActive;
  }

  throw new ApiError(400, 'Не найден активный шаблон для генерации договора.');
};

const normalizeSettingsCompanyProfile = (value, fallbackId = 'company-1') => {
  const legalType = toCounterpartyType(value?.legalType, value?.companyName);
  const bankAccounts = normalizeBankAccounts(value?.bankAccounts, value);
  const primaryBankAccount = getPrimaryBankAccount(bankAccounts, value);

  return {
    id: isNonEmptyString(value?.id) ? value.id.trim() : fallbackId,
    legalType,
    companyName: legalType === 'person' ? String(value?.companyName ?? '').trim() : toTrimmedString(value?.companyName),
    inn: toTrimmedString(value?.inn),
    kpp: legalType === 'ooo' ? toTrimmedString(value?.kpp) : '',
    ogrn: legalType === 'ooo' ? toTrimmedString(value?.ogrn) : '',
    ogrnip: legalType === 'ip' ? toTrimmedString(value?.ogrnip) : '',
    directorGenitive: legalType === 'person' ? '' : toTrimmedString(value?.directorGenitive),
    legalAddress:
      legalType === 'person'
        ? toTrimmedString(value?.registrationAddress || value?.legalAddress)
        : toTrimmedString(value?.legalAddress),
    email: toTrimmedString(value?.email),
    phone: toTrimmedString(value?.phone),
    bankAccounts,
    bankName: primaryBankAccount.bankName,
    checkingAccount: primaryBankAccount.checkingAccount,
    correspondentAccount: primaryBankAccount.correspondentAccount,
    bik: primaryBankAccount.bik,
    cardNumber: toTrimmedString(primaryBankAccount.cardNumber),
    sbpPhone: toTrimmedString(primaryBankAccount.sbpPhone) || (legalType === 'person' ? toTrimmedString(value?.phone) : ''),
    passportSeries: legalType === 'person' ? toTrimmedString(value?.passportSeries) : '',
    passportNumber: legalType === 'person' ? toTrimmedString(value?.passportNumber) : '',
    passportIssuedBy: legalType === 'person' ? toTrimmedString(value?.passportIssuedBy) : '',
    passportIssuedDate: legalType === 'person' ? toTrimmedString(value?.passportIssuedDate) : '',
    passportDepartmentCode: legalType === 'person' ? toTrimmedString(value?.passportDepartmentCode) : '',
    registrationAddress:
      legalType === 'person'
        ? toTrimmedString(value?.registrationAddress || value?.legalAddress)
        : '',
    residenceAddress: legalType === 'person' ? toTrimmedString(value?.residenceAddress) : '',
  };
};

const privateSellerRfToSettingsCompanyProfile = (privateSellerRf, fallbackId = 'person-rf') =>
  normalizeSettingsCompanyProfile(
    {
      id: fallbackId,
      legalType: 'person',
      companyName: privateSellerRf?.fullName,
      legalAddress: privateSellerRf?.registrationAddress,
      registrationAddress: privateSellerRf?.registrationAddress,
      residenceAddress: privateSellerRf?.residenceAddress,
      phone: privateSellerRf?.phone,
      email: privateSellerRf?.email,
      passportSeries: privateSellerRf?.passportSeries,
      passportNumber: privateSellerRf?.passportNumber,
      passportIssuedBy: privateSellerRf?.passportIssuedBy,
      passportIssuedDate: privateSellerRf?.passportIssuedDate,
      passportDepartmentCode: privateSellerRf?.passportDepartmentCode,
      bankName: privateSellerRf?.bankName,
      cardNumber: privateSellerRf?.cardNumber,
      sbpPhone: privateSellerRf?.sbpPhone,
      bik: privateSellerRf?.bik,
      checkingAccount: privateSellerRf?.checkingAccount,
      correspondentAccount: privateSellerRf?.correspondentAccount,
      bankAccounts: [
        {
          bankName: privateSellerRf?.bankName,
          cardNumber: privateSellerRf?.cardNumber,
          sbpPhone: privateSellerRf?.sbpPhone,
          bik: privateSellerRf?.bik,
          checkingAccount: privateSellerRf?.checkingAccount,
          correspondentAccount: privateSellerRf?.correspondentAccount,
        },
      ],
    },
    fallbackId
  );

const settingsPersonCompanyProfileToPrivateSellerRf = (profile) => {
  const normalizedProfile = normalizeSettingsCompanyProfile(profile, isNonEmptyString(profile?.id) ? profile.id : 'person-rf');
  const primaryBankAccount = getPrimaryBankAccount(normalizedProfile.bankAccounts, normalizedProfile);
  return normalizePrivatePersonRfProfile({
    fullName: normalizedProfile.companyName,
    passportSeries: normalizedProfile.passportSeries,
    passportNumber: normalizedProfile.passportNumber,
    passportIssuedBy: normalizedProfile.passportIssuedBy,
    passportIssuedDate: normalizedProfile.passportIssuedDate,
    passportDepartmentCode: normalizedProfile.passportDepartmentCode,
    registrationAddress: normalizedProfile.registrationAddress || normalizedProfile.legalAddress,
    residenceAddress: normalizedProfile.residenceAddress,
    phone: normalizedProfile.phone,
    email: normalizedProfile.email,
    bankName: primaryBankAccount.bankName || normalizedProfile.bankName,
    cardNumber: primaryBankAccount.cardNumber || normalizedProfile.cardNumber,
    sbpPhone: primaryBankAccount.sbpPhone || normalizedProfile.sbpPhone || normalizedProfile.phone,
    bik: primaryBankAccount.bik || normalizedProfile.bik,
    checkingAccount: primaryBankAccount.checkingAccount || normalizedProfile.checkingAccount,
    correspondentAccount: primaryBankAccount.correspondentAccount || normalizedProfile.correspondentAccount,
  });
};

const buildSettingsProfileFromLegacy = (settings) =>
  normalizeSettingsCompanyProfile(
    {
      id: isNonEmptyString(settings?.activeCompanyProfileId) ? settings.activeCompanyProfileId : 'company-1',
      legalType: settings?.legalType,
      companyName: settings?.companyName,
      inn: settings?.inn,
      kpp: settings?.kpp,
      ogrn: settings?.ogrn,
      ogrnip: settings?.ogrnip,
      directorGenitive: settings?.directorGenitive,
      legalAddress: settings?.legalAddress,
      email: settings?.email,
      phone: settings?.phone,
      bankName: settings?.bankName,
      cardNumber: settings?.cardNumber,
      sbpPhone: settings?.sbpPhone,
      checkingAccount: settings?.checkingAccount,
      correspondentAccount: settings?.correspondentAccount,
      bik: settings?.bik,
      bankAccounts: settings?.bankAccounts,
    },
    'company-1'
  );

const SETTINGS_PROFILE_PATCH_KEYS = [
  'legalType',
  'companyName',
  'inn',
  'kpp',
  'ogrn',
  'ogrnip',
  'directorGenitive',
  'legalAddress',
  'email',
  'phone',
  'bankName',
  'cardNumber',
  'sbpPhone',
  'checkingAccount',
  'correspondentAccount',
  'bik',
  'bankAccounts',
];

const normalizeSettingsPayload = (settings, patch = null) => {
  const source = settings && typeof settings === 'object' ? settings : {};
  const merged = { ...deepClone(DEFAULT_DATA.settings), ...source };
  const privateSellerRf = normalizePrivatePersonRfProfile(merged.privateSellerRf);

  let companyProfiles = Array.isArray(merged.companyProfiles)
    ? merged.companyProfiles.map((profile, index) =>
        normalizeSettingsCompanyProfile(
          profile,
          isNonEmptyString(profile?.id) ? profile.id : `company-${index + 1}`
        )
      )
    : [];

  if (companyProfiles.length === 0) {
    companyProfiles = [buildSettingsProfileFromLegacy(merged)];
  }

  if (!companyProfiles.some((profile) => toCounterpartyType(profile?.legalType, profile?.companyName) === 'person') && hasPrivateSellerRfValues(privateSellerRf)) {
    companyProfiles.push(
      privateSellerRfToSettingsCompanyProfile(
        privateSellerRf,
        isNonEmptyString(merged.activeCompanyProfileId) ? `${merged.activeCompanyProfileId}-person` : 'person-rf'
      )
    );
  }

  const requestedActiveCompanyProfileId = isNonEmptyString(merged.activeCompanyProfileId)
    ? merged.activeCompanyProfileId.trim()
    : companyProfiles[0].id;
  const activeProfileIndex = Math.max(
    0,
    companyProfiles.findIndex((profile) => profile.id === requestedActiveCompanyProfileId)
  );

  const patchObject = patch && typeof patch === 'object' ? patch : null;
  const hasLegacyPatch = patchObject
    ? SETTINGS_PROFILE_PATCH_KEYS.some((key) => Object.prototype.hasOwnProperty.call(patchObject, key))
    : false;

  if (hasLegacyPatch) {
    const profileToPatch = companyProfiles[activeProfileIndex];
    const nextProfile = { ...profileToPatch };

    SETTINGS_PROFILE_PATCH_KEYS.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(patchObject, key)) {
        nextProfile[key] = patchObject[key];
      }
    });

    companyProfiles[activeProfileIndex] = normalizeSettingsCompanyProfile(nextProfile, profileToPatch.id);
  }

  const activeProfile = companyProfiles[activeProfileIndex];
  const personProfile = companyProfiles.find((profile) => toCounterpartyType(profile?.legalType, profile?.companyName) === 'person');
  const syncedPrivateSellerRf = personProfile
    ? settingsPersonCompanyProfileToPrivateSellerRf(personProfile)
    : privateSellerRf;

  return {
    ...merged,
    companyProfiles,
    activeCompanyProfileId: activeProfile.id,
    privateSellerRf: syncedPrivateSellerRf,
    legalType: activeProfile.legalType,
    companyName: activeProfile.companyName,
    inn: activeProfile.inn,
    kpp: activeProfile.kpp,
    ogrn: activeProfile.ogrn,
    ogrnip: activeProfile.ogrnip,
    directorGenitive: activeProfile.directorGenitive,
    legalAddress: activeProfile.legalAddress,
    email: activeProfile.email,
    phone: activeProfile.phone,
    bankAccounts: activeProfile.bankAccounts,
    bankName: activeProfile.bankName,
    cardNumber: activeProfile.cardNumber,
    sbpPhone: activeProfile.sbpPhone,
    checkingAccount: activeProfile.checkingAccount,
    correspondentAccount: activeProfile.correspondentAccount,
    bik: activeProfile.bik,
  };
};

const getSettingsFromDb = () => {
  const row = getDb().prepare('SELECT payload_json FROM app_settings WHERE id = 1').get();
  if (!row) {
    return normalizeSettingsPayload(DEFAULT_DATA.settings);
  }

  const parsed = parseJsonSafe(row.payload_json, DEFAULT_DATA.settings);
  if (!parsed || typeof parsed !== 'object') {
    return normalizeSettingsPayload(DEFAULT_DATA.settings);
  }

  return normalizeSettingsPayload(parsed);
};

const setSettingsInDb = (settings) => {
  const normalizedSettings = normalizeSettingsPayload(settings);
  getDb()
    .prepare(
      `INSERT INTO app_settings (id, payload_json)
       VALUES (1, ?)
       ON CONFLICT(id) DO UPDATE SET payload_json = excluded.payload_json`
    )
    .run(stringifyJsonSafe(normalizedSettings, DEFAULT_DATA.settings));
};

const updateSettingsInDb = (patch) => {
  const current = getSettingsFromDb();
  const next = normalizeSettingsPayload({ ...current, ...patch }, patch);
  setSettingsInDb(next);
  return next;
};

const listInvoicesFromDb = () => {
  const rows = getDb()
    .prepare(
      `SELECT id, number, date, payment_due_date, amount, currency, status, commission_percent, vat_rate, vat_mode, supplier_profile_id, supplier_bank_account_json, items_json, counterparty_id
       FROM invoices
       ORDER BY sort_order DESC`
    )
    .all();

  return rows.map(mapInvoiceRow);
};

const getInvoiceByIdFromDb = (id) => {
  const row = getDb()
    .prepare(
      `SELECT id, number, date, payment_due_date, amount, currency, status, commission_percent, vat_rate, vat_mode, supplier_profile_id, supplier_bank_account_json, items_json, counterparty_id
       FROM invoices
       WHERE id = ?`
    )
    .get(id);

  return row ? mapInvoiceRow(row) : null;
};

const listContractsFromDb = (limit = 0) => {
  if (limit > 0) {
    const rows = getDb()
      .prepare(
        `SELECT id, number, title, type, counterparty_json, status, created_at, amount, supplier_profile_id, invoice_id, payment_terms, include_delivery, delivery_date, vat_rate, vat_mode, markup_percent, markup_mode, markup_calc_mode, template_id, template_name, template_version, contract_data_json, html_snapshot, snapshot_css
         FROM contracts
         ORDER BY sort_order DESC
         LIMIT ?`
      )
      .all(limit);

    return rows.map(mapContractRow);
  }

  const rows = getDb()
    .prepare(
      `SELECT id, number, title, type, counterparty_json, status, created_at, amount, supplier_profile_id, invoice_id, payment_terms, include_delivery, delivery_date, vat_rate, vat_mode, markup_percent, markup_mode, markup_calc_mode, template_id, template_name, template_version, contract_data_json, html_snapshot, snapshot_css
       FROM contracts
       ORDER BY sort_order DESC`
    )
    .all();

  return rows.map(mapContractRow);
};

const getContractByIdFromDb = (id) => {
  const row = getDb()
    .prepare(
      `SELECT id, number, title, type, counterparty_json, status, created_at, amount, supplier_profile_id, invoice_id, payment_terms, include_delivery, delivery_date, vat_rate, vat_mode, markup_percent, markup_mode, markup_calc_mode, template_id, template_name, template_version, contract_data_json, html_snapshot, snapshot_css
       FROM contracts
       WHERE id = ?`
    )
    .get(id);

  return row ? mapContractRow(row) : null;
};

const insertContractToDb = (contract) => {
  const nextSortOrder = getNextSortOrder('contracts');

  getDb()
    .prepare(
      `INSERT INTO contracts (
         id,
         sort_order,
         number,
         title,
         type,
         counterparty_json,
         status,
         created_at,
         amount,
         supplier_profile_id,
         invoice_id,
         payment_terms,
         include_delivery,
         delivery_date,
         vat_rate,
         vat_mode,
         markup_percent,
         markup_mode,
         markup_calc_mode,
         template_id,
         template_name,
         template_version,
         contract_data_json,
         html_snapshot,
         snapshot_css
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      contract.id,
      nextSortOrder,
      contract.number,
      contract.title,
      contract.type,
      stringifyJsonSafe(contract.counterparty, {}),
      contract.status,
      contract.createdAt,
      contract.amount == null ? null : Number(contract.amount),
      isNonEmptyString(contract.supplierProfileId) ? contract.supplierProfileId : null,
      contract.invoiceId || null,
      contract.paymentTerms == null ? null : Number(contract.paymentTerms),
      contract.includeDelivery ? 1 : 0,
      contract.deliveryDate == null ? null : contract.deliveryDate,
      toVatRate(contract.vatRate),
      toVatMode(contract.vatMode),
      toMarkupPercent(contract.markupPercent),
      toMarkupMode(contract.markupMode),
      toMarkupCalcMode(contract.markupCalcMode),
      toTrimmedString(contract.templateId),
      toTrimmedString(contract.templateName),
      toTrimmedString(contract.templateVersion),
      stringifyJsonSafe(contract.contractData, {}),
      isNonEmptyString(contract.htmlSnapshot) ? contract.htmlSnapshot : '',
      isNonEmptyString(contract.snapshotCss) ? contract.snapshotCss : ''
    );
};

const saveContractByIdToDb = (contractId, contract) => {
  getDb()
    .prepare(
      `UPDATE contracts
       SET number = ?,
           title = ?,
           type = ?,
           counterparty_json = ?,
           status = ?,
           created_at = ?,
           amount = ?,
           supplier_profile_id = ?,
           invoice_id = ?,
           payment_terms = ?,
           include_delivery = ?,
           delivery_date = ?,
           vat_rate = ?,
           vat_mode = ?,
           markup_percent = ?,
           markup_mode = ?,
           markup_calc_mode = ?,
           template_id = ?,
           template_name = ?,
           template_version = ?,
           contract_data_json = ?,
           html_snapshot = ?,
           snapshot_css = ?
       WHERE id = ?`
    )
    .run(
      toTrimmedString(contract.number),
      toTrimmedString(contract.title),
      toTrimmedString(contract.type),
      stringifyJsonSafe(contract.counterparty, {}),
      toContractStatus(contract.status, CONTRACT_STATUS.DRAFT),
      isNonEmptyString(contract.createdAt) ? contract.createdAt : formatDate(),
      contract.amount == null ? null : toNonNegativeNumber(contract.amount, 0),
      isNonEmptyString(contract.supplierProfileId) ? contract.supplierProfileId : null,
      isNonEmptyString(contract.invoiceId) ? contract.invoiceId : null,
      contract.paymentTerms == null ? null : toPositiveInteger(contract.paymentTerms, 0),
      contract.includeDelivery ? 1 : 0,
      contract.deliveryDate == null ? null : contract.deliveryDate,
      toVatRate(contract.vatRate),
      toVatMode(contract.vatMode),
      toMarkupPercent(contract.markupPercent),
      toMarkupMode(contract.markupMode),
      toMarkupCalcMode(contract.markupCalcMode),
      toTrimmedString(contract.templateId),
      toTrimmedString(contract.templateName),
      toTrimmedString(contract.templateVersion),
      stringifyJsonSafe(contract.contractData, {}),
      isNonEmptyString(contract.htmlSnapshot) ? contract.htmlSnapshot : '',
      isNonEmptyString(contract.snapshotCss) ? contract.snapshotCss : '',
      contractId
    );
};

const deleteContractByIdInDb = (contractId) => {
  const existing = getContractByIdFromDb(contractId);
  if (!existing) {
    throw new ApiError(404, 'Договор не найден.');
  }

  getDb().prepare('DELETE FROM contracts WHERE id = ?').run(contractId);
};

const insertCounterpartyToDb = (counterparty) => {
  const nextSortOrder = getNextSortOrder('counterparties');
  const legalType = toCounterpartyType(counterparty.legalType, counterparty.name);
  const bankAccounts = normalizeBankAccounts(counterparty.bankAccounts, counterparty);
  const primaryBankAccount = getPrimaryBankAccount(bankAccounts, counterparty);

  getDb()
    .prepare(
      `INSERT INTO counterparties (
         id,
         sort_order,
         name,
         inn,
         address,
         contact_person,
         email,
         phone,
         legal_type,
         director_name,
         ogrn,
         kpp,
         ogrnip,
         passport_series,
         passport_number,
         passport_issued_by,
         passport_issued_date,
         passport_department_code,
         registration_address,
         residence_address,
         bank_name,
         checking_account,
         correspondent_account,
         bik,
         bank_accounts_json
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      counterparty.id,
      nextSortOrder,
      toTrimmedString(counterparty.name),
      toTrimmedString(counterparty.inn),
      toTrimmedString(counterparty.address),
      toTrimmedString(counterparty.contactPerson),
      toTrimmedString(counterparty.email),
      toTrimmedString(counterparty.phone),
      legalType,
      toTrimmedString(counterparty.directorName),
      toTrimmedString(counterparty.ogrn),
      toTrimmedString(counterparty.kpp),
      toTrimmedString(counterparty.ogrnip),
      toTrimmedString(counterparty.passportSeries),
      toTrimmedString(counterparty.passportNumber),
      toTrimmedString(counterparty.passportIssuedBy),
      toTrimmedString(counterparty.passportIssuedDate),
      toTrimmedString(counterparty.passportDepartmentCode),
      toTrimmedString(counterparty.registrationAddress),
      toTrimmedString(counterparty.residenceAddress),
      primaryBankAccount.bankName,
      primaryBankAccount.checkingAccount,
      primaryBankAccount.correspondentAccount,
      primaryBankAccount.bik,
      stringifyJsonSafe(bankAccounts, [])
    );
};

const insertInvoiceToDb = (invoice) => {
  const nextSortOrder = getNextSortOrder('invoices');

  getDb()
    .prepare(
      `INSERT INTO invoices (id, sort_order, number, date, payment_due_date, amount, currency, status, commission_percent, vat_rate, vat_mode, supplier_profile_id, supplier_bank_account_json, items_json, counterparty_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      invoice.id,
      nextSortOrder,
      invoice.number,
      invoice.date,
      isNonEmptyString(invoice.paymentDueDate) ? invoice.paymentDueDate : null,
      Number(invoice.amount || 0),
      toCurrency(invoice.currency),
      toInvoiceStatus(invoice.status),
      toMarkupPercent(invoice.commissionPercent),
      toVatRate(invoice.vatRate),
      toVatMode(invoice.vatMode),
      isNonEmptyString(invoice.supplierProfileId) ? invoice.supplierProfileId : null,
      stringifyJsonSafe(toSupplierBankAccount(invoice.supplierBankAccount) || null, null),
      stringifyJsonSafe(Array.isArray(invoice.items) ? invoice.items : [], []),
      invoice.counterpartyId || null
    );
};

const saveInvoiceByIdToDb = (invoiceId, invoice) => {
  getDb()
    .prepare(
      `UPDATE invoices
       SET number = ?, date = ?, payment_due_date = ?, amount = ?, currency = ?, status = ?, commission_percent = ?, vat_rate = ?, vat_mode = ?, supplier_profile_id = ?, supplier_bank_account_json = ?, items_json = ?, counterparty_id = ?
       WHERE id = ?`
    )
    .run(
      toTrimmedString(invoice.number),
      toTrimmedString(invoice.date),
      isNonEmptyString(invoice.paymentDueDate) ? invoice.paymentDueDate : null,
      toNonNegativeNumber(invoice.amount, 0),
      toCurrency(invoice.currency),
      toInvoiceStatus(invoice.status),
      toMarkupPercent(invoice.commissionPercent),
      toVatRate(invoice.vatRate),
      toVatMode(invoice.vatMode),
      isNonEmptyString(invoice.supplierProfileId) ? invoice.supplierProfileId : null,
      stringifyJsonSafe(toSupplierBankAccount(invoice.supplierBankAccount) || null, null),
      stringifyJsonSafe(Array.isArray(invoice.items) ? invoice.items : [], []),
      isNonEmptyString(invoice.counterpartyId) ? invoice.counterpartyId : null,
      invoiceId
    );
};

const deleteInvoiceByIdInDb = (invoiceId) => {
  const existing = getInvoiceByIdFromDb(invoiceId);
  if (!existing) {
    throw new ApiError(404, 'Счёт не найден.');
  }

  const linkedContracts = listContractsFromDb().filter((contract) => contract.invoiceId === invoiceId);
  if (linkedContracts.length > 0) {
    throw new ApiError(409, 'Нельзя удалить счёт: сначала удалите или отвяжите связанные договоры.');
  }

  getDb().prepare('DELETE FROM invoices WHERE id = ?').run(invoiceId);
};

const deleteCounterpartyByIdInDb = (counterpartyId) => {
  const existing = getCounterpartyByIdFromDb(counterpartyId);
  if (!existing) {
    throw new ApiError(404, 'Контрагент не найден.');
  }

  const linkedContractsCount = listContractsFromDb().filter((contract) => contract.counterparty?.id === counterpartyId).length;
  if (linkedContractsCount > 0) {
    throw new ApiError(409, 'Нельзя удалить контрагента: у него есть связанные договоры.');
  }

  const linkedInvoicesRow = getDb()
    .prepare('SELECT COUNT(*) AS count FROM invoices WHERE counterparty_id = ?')
    .get(counterpartyId);
  const linkedInvoicesCount = Number(linkedInvoicesRow?.count || 0);
  if (linkedInvoicesCount > 0) {
    throw new ApiError(409, 'Нельзя удалить контрагента: у него есть связанные счета.');
  }

  getDb().prepare('DELETE FROM counterparties WHERE id = ?').run(counterpartyId);
};

const resolveTemplateForContractSnapshot = ({ templateId, type, fallbackTemplateId }) => {
  if (isNonEmptyString(templateId)) {
    const byId = getTemplateByIdFromDb(templateId);
    if (!byId) {
      throw new ApiError(404, 'Шаблон не найден.');
    }
    if (!byId.isActive) {
      throw new ApiError(400, 'Выбранный шаблон отключен.');
    }
    return byId;
  }

  if (isNonEmptyString(fallbackTemplateId)) {
    const existingTemplate = getTemplateByIdFromDb(fallbackTemplateId);
    if (existingTemplate) {
      return existingTemplate;
    }
  }

  const templates = listTemplatesFromDb();
  const activeByType = templates.find((template) => template.type === type && template.isActive);
  if (activeByType) {
    return activeByType;
  }

  const firstActive = templates.find((template) => template.isActive);
  if (firstActive) {
    return firstActive;
  }

  throw new ApiError(400, 'Не найден активный шаблон для генерации договора.');
};

const assertSupplyLegalEntitiesTemplateCompatibility = ({ template, counterparty, settings, supplierProfileId }) => {
  if (!template || template.id !== SUPPLY_LEGAL_ENTITIES_TEMPLATE_ID) {
    return;
  }

  if (!counterparty || typeof counterparty !== 'object') {
    throw new ApiError(400, 'Для шаблона "Договор поставки (юрлица и ИП, расширенный)" требуется выбранный Покупатель.');
  }

  const supplierProfile = resolveSupplierProfileFromSettings(settings, supplierProfileId);
  const supplierType = toCounterpartyType(supplierProfile?.legalType, supplierProfile?.companyName);
  const buyerType = toCounterpartyType(counterparty?.legalType, counterparty?.name);

  if (!SUPPLY_LEGAL_ENTITY_TYPES.has(supplierType) || !SUPPLY_LEGAL_ENTITY_TYPES.has(buyerType)) {
    throw new ApiError(
      400,
      'Шаблон "Договор поставки (юрлица и ИП, расширенный)" доступен только для сторон типов ООО, АО или ИП. Физлица не поддерживаются.'
    );
  }
};

const buildContractSnapshotPayload = ({ contract, counterparty, invoice, templateId }) => {
  const template = resolveTemplateForContractSnapshot({
    templateId,
    type: contract.type,
    fallbackTemplateId: contract.templateId,
  });
  const settings = getSettingsFromDb();
  assertSupplyLegalEntitiesTemplateCompatibility({
    template,
    counterparty,
    settings,
    supplierProfileId: invoice?.supplierProfileId || contract?.supplierProfileId,
  });
  const contractData = buildContractTemplateContext({
    contract,
    counterparty,
    invoice,
    settings,
  });
  const htmlSnapshot = renderTemplateContent(normalizeTemplateContent(template.content), contractData);
  if (!isNonEmptyString(htmlSnapshot)) {
    throw new ApiError(500, 'Не удалось сформировать HTML-слепок договора.');
  }

  return {
    ...contract,
    templateId: template.id,
    templateName: template.name,
    templateVersion: template.version,
    contractData,
    htmlSnapshot,
    snapshotCss: normalizeTemplateCss(template.css),
  };
};

const updateContractByIdInDb = (contractId, patch) => {
  const existing = getContractByIdFromDb(contractId);
  if (!existing) {
    throw new ApiError(404, 'Договор не найден.');
  }

  const hasCounterpartyPatch = Object.prototype.hasOwnProperty.call(patch, 'counterpartyId');
  const hasInvoicePatch = Object.prototype.hasOwnProperty.call(patch, 'invoiceId');
  const hasTemplatePatch = Object.prototype.hasOwnProperty.call(patch, 'templateId');
  const hasAmountPatch = Object.prototype.hasOwnProperty.call(patch, 'amount');
  const hasDeliveryPatch = Object.prototype.hasOwnProperty.call(patch, 'deliveryDate');
  const hasStatusPatch = Object.prototype.hasOwnProperty.call(patch, 'status');
  const hasContractDataPatch = Object.prototype.hasOwnProperty.call(patch, 'contractData');

  if (hasStatusPatch) {
    const normalizedStatus = String(patch.status ?? '').trim();
    if (!VALID_CONTRACT_STATUSES.has(normalizedStatus)) {
      throw new ApiError(400, 'Некорректный статус договора.');
    }
  }

  const nextType = isNonEmptyString(patch?.type) ? patch.type.trim() : existing.type;

  let counterparty = existing.counterparty;
  if (hasCounterpartyPatch) {
    if (!isNonEmptyString(patch.counterpartyId)) {
      throw new ApiError(400, 'Поле "counterpartyId" обязательно.');
    }
    counterparty = getCounterpartyByIdFromDb(patch.counterpartyId.trim());
    if (!counterparty) {
      throw new ApiError(404, 'Контрагент не найден.');
    }
  } else if (isNonEmptyString(existing.counterparty?.id)) {
    counterparty = getCounterpartyByIdFromDb(existing.counterparty.id) || existing.counterparty;
  }

  let invoice = existing.invoiceId ? getInvoiceByIdFromDb(existing.invoiceId) : null;
  if (hasInvoicePatch) {
    if (!isNonEmptyString(patch.invoiceId)) {
      invoice = null;
    } else {
      invoice = getInvoiceByIdFromDb(patch.invoiceId.trim());
      if (!invoice) {
        throw new ApiError(404, 'Счёт не найден.');
      }
    }
  }

  const fallbackAmount = invoice ? Number(invoice.amount || 0) : Number(existing.amount || 0);
  const normalizedAmount =
    hasAmountPatch && patch.amount == null ? undefined : toNonNegativeNumber(hasAmountPatch ? patch.amount : existing.amount, fallbackAmount);
  const includeDelivery =
    typeof patch?.includeDelivery === 'boolean' ? patch.includeDelivery : Boolean(existing.includeDelivery);
  const rawDeliveryDate = hasDeliveryPatch ? patch.deliveryDate : existing.deliveryDate;
  const deliveryDate = includeDelivery && isNonEmptyString(rawDeliveryDate) ? rawDeliveryDate.trim() : null;
  const templateIdCandidate = hasTemplatePatch && isNonEmptyString(patch.templateId) ? patch.templateId.trim() : undefined;
  const invoiceCommissionPercent = invoice ? toMarkupPercent(invoice.commissionPercent) : null;
  const nextContractData = hasContractDataPatch
    ? {
        ...(existing.contractData && typeof existing.contractData === 'object' ? existing.contractData : {}),
        ...(patch.contractData && typeof patch.contractData === 'object' ? patch.contractData : {}),
      }
    : existing.contractData;

  const nextContract = {
    ...existing,
    number: isNonEmptyString(patch?.number) ? patch.number.trim() : existing.number,
    title: isNonEmptyString(patch?.title) ? patch.title.trim() : buildContractTitle(nextType, counterparty),
    type: nextType,
    counterparty,
    status: hasStatusPatch ? toContractStatus(patch.status, existing.status) : toContractStatus(existing.status),
    amount: normalizedAmount,
    supplierProfileId: resolveSupplierProfileIdForContract(invoice, existing.supplierProfileId),
    invoiceId: invoice ? invoice.id : undefined,
    paymentTerms: Object.prototype.hasOwnProperty.call(patch, 'paymentTerms')
      ? toPositiveInteger(patch.paymentTerms, existing.paymentTerms || 10)
      : existing.paymentTerms,
    includeDelivery,
    deliveryDate,
    vatRate:
      invoice != null
        ? toVatRate(invoice.vatRate)
        : Object.prototype.hasOwnProperty.call(patch, 'vatRate')
          ? toVatRate(patch.vatRate)
          : toVatRate(existing.vatRate),
    vatMode:
      invoice != null
        ? toVatMode(invoice.vatMode)
        : Object.prototype.hasOwnProperty.call(patch, 'vatMode')
          ? toVatMode(patch.vatMode)
          : toVatMode(existing.vatMode),
    markupPercent:
      invoiceCommissionPercent == null
        ? Object.prototype.hasOwnProperty.call(patch, 'markupPercent')
          ? toMarkupPercent(patch.markupPercent)
          : toMarkupPercent(existing.markupPercent)
        : invoiceCommissionPercent,
    markupMode: Object.prototype.hasOwnProperty.call(patch, 'markupMode')
      ? toMarkupMode(patch.markupMode)
      : toMarkupMode(existing.markupMode),
    markupCalcMode: Object.prototype.hasOwnProperty.call(patch, 'markupCalcMode')
      ? toMarkupCalcMode(patch.markupCalcMode)
      : toMarkupCalcMode(existing.markupCalcMode),
    contractData: nextContractData && typeof nextContractData === 'object' ? nextContractData : {},
  };

  const nextWithSnapshot = buildContractSnapshotPayload({
    contract: nextContract,
    counterparty,
    invoice,
    templateId: templateIdCandidate,
  });

  saveContractByIdToDb(contractId, nextWithSnapshot);

  const updated = getContractByIdFromDb(contractId);
  if (!updated) {
    throw new ApiError(500, 'Не удалось обновить договор.');
  }

  return updated;
};

const updateCounterpartyByIdInDb = (counterpartyId, patch) => {
  const existing = getCounterpartyByIdFromDb(counterpartyId);
  if (!existing) {
    throw new ApiError(404, 'Контрагент не найден.');
  }

  const hasBankAccountsPatch = Object.prototype.hasOwnProperty.call(patch, 'bankAccounts');
  const hasLegacyBankPatch =
    Object.prototype.hasOwnProperty.call(patch, 'bankName') ||
    Object.prototype.hasOwnProperty.call(patch, 'checkingAccount') ||
    Object.prototype.hasOwnProperty.call(patch, 'correspondentAccount') ||
    Object.prototype.hasOwnProperty.call(patch, 'bik');
  const existingBankAccounts = normalizeBankAccounts(existing.bankAccounts, existing);

  let nextBankAccounts = existingBankAccounts;
  if (hasBankAccountsPatch) {
    nextBankAccounts = normalizeBankAccounts(patch.bankAccounts);
  } else if (hasLegacyBankPatch) {
    const primaryFromPatch = {
      bankName: Object.prototype.hasOwnProperty.call(patch, 'bankName') ? patch.bankName : existing.bankName,
      checkingAccount: Object.prototype.hasOwnProperty.call(patch, 'checkingAccount')
        ? patch.checkingAccount
        : existing.checkingAccount,
      correspondentAccount: Object.prototype.hasOwnProperty.call(patch, 'correspondentAccount')
        ? patch.correspondentAccount
        : existing.correspondentAccount,
      bik: Object.prototype.hasOwnProperty.call(patch, 'bik') ? patch.bik : existing.bik,
    };
    nextBankAccounts = normalizeBankAccounts([primaryFromPatch, ...existingBankAccounts.slice(1)]);
  }

  const primaryBankAccount = getPrimaryBankAccount(nextBankAccounts);

  const nextLegalType = toCounterpartyType(
      Object.prototype.hasOwnProperty.call(patch, 'legalType') ? patch.legalType : existing.legalType,
      Object.prototype.hasOwnProperty.call(patch, 'name') ? patch.name : existing.name
    );

  const next = {
    legalType: nextLegalType,
    name: Object.prototype.hasOwnProperty.call(patch, 'name') ? toTrimmedString(patch.name) : existing.name,
    inn: Object.prototype.hasOwnProperty.call(patch, 'inn') ? toTrimmedString(patch.inn) : existing.inn,
    address: Object.prototype.hasOwnProperty.call(patch, 'address') ? toTrimmedString(patch.address) : existing.address,
    contactPerson: Object.prototype.hasOwnProperty.call(patch, 'contactPerson')
      ? toTrimmedString(patch.contactPerson)
      : existing.contactPerson,
    email: Object.prototype.hasOwnProperty.call(patch, 'email') ? toTrimmedString(patch.email) : existing.email,
    phone: Object.prototype.hasOwnProperty.call(patch, 'phone') ? toTrimmedString(patch.phone) : toTrimmedString(existing.phone),
    directorName: Object.prototype.hasOwnProperty.call(patch, 'directorName')
      ? toTrimmedString(patch.directorName)
      : toTrimmedString(existing.directorName),
    ogrn: Object.prototype.hasOwnProperty.call(patch, 'ogrn') ? toTrimmedString(patch.ogrn) : toTrimmedString(existing.ogrn),
    kpp: Object.prototype.hasOwnProperty.call(patch, 'kpp') ? toTrimmedString(patch.kpp) : toTrimmedString(existing.kpp),
    ogrnip: Object.prototype.hasOwnProperty.call(patch, 'ogrnip')
      ? toTrimmedString(patch.ogrnip)
      : toTrimmedString(existing.ogrnip),
    passportSeries: Object.prototype.hasOwnProperty.call(patch, 'passportSeries')
      ? toTrimmedString(patch.passportSeries)
      : toTrimmedString(existing.passportSeries),
    passportNumber: Object.prototype.hasOwnProperty.call(patch, 'passportNumber')
      ? toTrimmedString(patch.passportNumber)
      : toTrimmedString(existing.passportNumber),
    passportIssuedBy: Object.prototype.hasOwnProperty.call(patch, 'passportIssuedBy')
      ? toTrimmedString(patch.passportIssuedBy)
      : toTrimmedString(existing.passportIssuedBy),
    passportIssuedDate: Object.prototype.hasOwnProperty.call(patch, 'passportIssuedDate')
      ? toTrimmedString(patch.passportIssuedDate)
      : toTrimmedString(existing.passportIssuedDate),
    passportDepartmentCode: Object.prototype.hasOwnProperty.call(patch, 'passportDepartmentCode')
      ? toTrimmedString(patch.passportDepartmentCode)
      : toTrimmedString(existing.passportDepartmentCode),
    registrationAddress: Object.prototype.hasOwnProperty.call(patch, 'registrationAddress')
      ? toTrimmedString(patch.registrationAddress)
      : toTrimmedString(existing.registrationAddress),
    residenceAddress: Object.prototype.hasOwnProperty.call(patch, 'residenceAddress')
      ? toTrimmedString(patch.residenceAddress)
      : toTrimmedString(existing.residenceAddress),
    bankAccounts: nextBankAccounts,
    bankName: primaryBankAccount.bankName,
    checkingAccount: primaryBankAccount.checkingAccount,
    correspondentAccount: primaryBankAccount.correspondentAccount,
    bik: primaryBankAccount.bik,
  };

  if (next.legalType === 'person' && !isNonEmptyString(next.address) && isNonEmptyString(next.registrationAddress)) {
    next.address = next.registrationAddress;
  }

  if (!isNonEmptyString(next.name)) {
    throw new ApiError(400, 'Поле "name" обязательно.');
  }
  if (next.legalType !== 'person' && !isNonEmptyString(next.inn)) {
    throw new ApiError(400, 'Поле "inn" обязательно.');
  }
  if ((next.legalType === 'ooo' || next.legalType === 'ao') && !isNonEmptyString(next.directorName)) {
    throw new ApiError(400, 'Для ООО/АО укажите руководителя в поле "directorName".');
  }

  getDb()
    .prepare(
      `UPDATE counterparties
       SET name = ?, inn = ?, address = ?, contact_person = ?, email = ?, phone = ?, legal_type = ?, director_name = ?, ogrn = ?, kpp = ?, ogrnip = ?, passport_series = ?, passport_number = ?, passport_issued_by = ?, passport_issued_date = ?, passport_department_code = ?, registration_address = ?, residence_address = ?, bank_name = ?, checking_account = ?, correspondent_account = ?, bik = ?, bank_accounts_json = ?
       WHERE id = ?`
    )
    .run(
      next.name,
      next.inn,
      next.address,
      next.contactPerson,
      next.email,
      next.phone,
      next.legalType,
      next.directorName,
      next.ogrn,
      next.kpp,
      next.ogrnip,
      next.passportSeries,
      next.passportNumber,
      next.passportIssuedBy,
      next.passportIssuedDate,
      next.passportDepartmentCode,
      next.registrationAddress,
      next.residenceAddress,
      next.bankName,
      next.checkingAccount,
      next.correspondentAccount,
      next.bik,
      stringifyJsonSafe(next.bankAccounts, []),
      counterpartyId
    );

  const updated = getCounterpartyByIdFromDb(counterpartyId);
  if (!updated) {
    throw new ApiError(500, 'Не удалось обновить контрагента.');
  }

  const linkedContracts = listContractsFromDb().filter((contract) => contract.counterparty?.id === counterpartyId);
  linkedContracts.forEach((contract) => {
    updateContractByIdInDb(contract.id, {
      counterpartyId,
      title: buildContractTitle(contract.type, updated),
    });
  });

  return updated;
};

const resolveSupplierProfileIdForInvoice = (candidateId, fallbackId = '') => {
  const settings = getSettingsFromDb();
  const profiles = Array.isArray(settings.companyProfiles) ? settings.companyProfiles : [];
  const activeProfileId = isNonEmptyString(settings.activeCompanyProfileId)
    ? settings.activeCompanyProfileId.trim()
    : profiles[0]?.id;

  const normalizedCandidate = toTrimmedString(candidateId);
  if (isNonEmptyString(normalizedCandidate)) {
    const exists = profiles.some((profile) => profile.id === normalizedCandidate);
    if (!exists) {
      throw new ApiError(400, 'Выбранный профиль компании не найден.');
    }
    return normalizedCandidate;
  }

  const normalizedFallback = toTrimmedString(fallbackId);
  if (isNonEmptyString(normalizedFallback)) {
    const exists = profiles.some((profile) => profile.id === normalizedFallback);
    if (exists) {
      return normalizedFallback;
    }
  }

  return isNonEmptyString(activeProfileId) ? activeProfileId : undefined;
};

const resolveSupplierProfileIdForContract = (invoice, fallbackId = '') => {
  if (invoice && isNonEmptyString(invoice.supplierProfileId)) {
    return invoice.supplierProfileId;
  }

  const settings = getSettingsFromDb();
  const profiles = Array.isArray(settings.companyProfiles) ? settings.companyProfiles : [];
  const activeProfileId = isNonEmptyString(settings.activeCompanyProfileId)
    ? settings.activeCompanyProfileId.trim()
    : profiles[0]?.id;

  if (isNonEmptyString(fallbackId)) {
    const exists = profiles.some((profile) => profile.id === fallbackId);
    if (exists) {
      return fallbackId;
    }
  }

  return isNonEmptyString(activeProfileId) ? activeProfileId : undefined;
};

const updateInvoiceByIdInDb = (invoiceId, patch) => {
  const existing = getInvoiceByIdFromDb(invoiceId);
  if (!existing) {
    throw new ApiError(404, 'Счёт не найден.');
  }

  let nextCounterpartyId = existing.counterpartyId;
  if (Object.prototype.hasOwnProperty.call(patch, 'counterpartyId')) {
    if (!isNonEmptyString(patch.counterpartyId)) {
      nextCounterpartyId = undefined;
    } else {
      const linkedCounterparty = getCounterpartyByIdFromDb(patch.counterpartyId.trim());
      if (!linkedCounterparty) {
        throw new ApiError(404, 'Контрагент не найден.');
      }
      nextCounterpartyId = linkedCounterparty.id;
    }
  }

  const hasItemsPatch = Object.prototype.hasOwnProperty.call(patch, 'items');
  const normalizedItems = hasItemsPatch ? normalizeInvoiceItems(patch.items) : normalizeInvoiceItems(existing.items);
  const calculatedAmount = normalizedItems.reduce(
    (sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0),
    0
  );
  const nextAmount = Object.prototype.hasOwnProperty.call(patch, 'amount')
    ? toNonNegativeNumber(patch.amount, calculatedAmount)
    : hasItemsPatch
      ? calculatedAmount
      : toNonNegativeNumber(existing.amount, calculatedAmount);
  const nextSupplierProfileId = Object.prototype.hasOwnProperty.call(patch, 'supplierProfileId')
    ? resolveSupplierProfileIdForInvoice(patch.supplierProfileId, existing.supplierProfileId)
    : resolveSupplierProfileIdForInvoice(existing.supplierProfileId);

  const nextInvoice = {
    ...existing,
    number: isNonEmptyString(patch?.number) ? patch.number.trim() : existing.number,
    date: isNonEmptyString(patch?.date) ? patch.date.trim() : existing.date,
    paymentDueDate: Object.prototype.hasOwnProperty.call(patch, 'paymentDueDate')
      ? isNonEmptyString(patch?.paymentDueDate)
        ? patch.paymentDueDate.trim()
        : undefined
      : existing.paymentDueDate,
    amount: nextAmount,
    currency: Object.prototype.hasOwnProperty.call(patch, 'currency') ? toCurrency(patch.currency) : toCurrency(existing.currency),
    status: Object.prototype.hasOwnProperty.call(patch, 'status') ? toInvoiceStatus(patch.status) : toInvoiceStatus(existing.status),
    commissionPercent: Object.prototype.hasOwnProperty.call(patch, 'commissionPercent')
      ? toMarkupPercent(patch.commissionPercent)
      : toMarkupPercent(existing.commissionPercent),
    vatRate: Object.prototype.hasOwnProperty.call(patch, 'vatRate') ? toVatRate(patch.vatRate) : toVatRate(existing.vatRate),
    vatMode: Object.prototype.hasOwnProperty.call(patch, 'vatMode') ? toVatMode(patch.vatMode) : toVatMode(existing.vatMode),
    supplierProfileId: nextSupplierProfileId,
    supplierBankAccount: Object.prototype.hasOwnProperty.call(patch, 'supplierBankAccount')
      ? toSupplierBankAccount(patch.supplierBankAccount)
      : toSupplierBankAccount(existing.supplierBankAccount),
    items: normalizedItems,
    counterpartyId: nextCounterpartyId,
  };

  saveInvoiceByIdToDb(invoiceId, nextInvoice);

  const updated = getInvoiceByIdFromDb(invoiceId);
  if (!updated) {
    throw new ApiError(500, 'Не удалось обновить счёт.');
  }

  const linkedContracts = listContractsFromDb().filter((contract) => contract.invoiceId === invoiceId);
  linkedContracts.forEach((contract) => {
    const oldAmount = toNonNegativeNumber(existing.amount, 0);
    const contractAmount = contract.amount == null ? null : toNonNegativeNumber(contract.amount, 0);
    const shouldSyncAmount = contractAmount == null || Math.abs(contractAmount - oldAmount) < 0.000001;

    updateContractByIdInDb(contract.id, {
      invoiceId,
      amount: shouldSyncAmount ? updated.amount : contract.amount,
      markupPercent: toMarkupPercent(updated.commissionPercent),
    });
  });

  return updated;
};

const bumpTemplateVersion = (currentVersion) => {
  const parsed = Number.parseFloat(String(currentVersion ?? '').replace(',', '.'));
  if (!Number.isFinite(parsed) || parsed < 0) {
    return '1.0';
  }

  const bumped = Math.round((parsed + 0.1) * 10) / 10;
  return bumped.toFixed(1);
};

const insertTemplateToDb = (template) => {
  const nextSortOrder = getNextSortOrder('templates');

  getDb()
    .prepare(
      `INSERT INTO templates (id, sort_order, name, type, version, updated_at, is_active, content_html, css_text, variables_json)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      template.id,
      nextSortOrder,
      toTrimmedString(template.name),
      toTrimmedString(template.type),
      toTrimmedString(template.version) || '1.0',
      isNonEmptyString(template.updatedAt) ? template.updatedAt : formatDate(),
      template.isActive === false ? 0 : 1,
      normalizeTemplateContent(template.content),
      normalizeTemplateCss(template.css),
      stringifyJsonSafe(normalizeTemplateVariables(template.variables), DEFAULT_TEMPLATE_VARIABLES)
    );
};

const updateTemplateByIdInDb = (templateId, patch) => {
  const existing = getTemplateByIdFromDb(templateId);
  if (!existing) {
    throw new ApiError(404, 'Шаблон не найден.');
  }

  const next = {
    name: isNonEmptyString(patch?.name) ? patch.name : existing.name,
    type: isNonEmptyString(patch?.type) ? patch.type : existing.type,
    version: isNonEmptyString(patch?.version) ? patch.version : bumpTemplateVersion(existing.version),
    updatedAt: formatDate(),
    isActive: typeof patch?.isActive === 'boolean' ? (patch.isActive ? 1 : 0) : (existing.isActive ? 1 : 0),
    content: normalizeTemplateContent(patch?.content ?? existing.content),
    css: normalizeTemplateCss(patch?.css ?? existing.css),
    variables: normalizeTemplateVariables(patch?.variables ?? existing.variables),
  };

  getDb()
    .prepare(
      `UPDATE templates
       SET name = ?, type = ?, version = ?, updated_at = ?, is_active = ?, content_html = ?, css_text = ?, variables_json = ?
       WHERE id = ?`
    )
    .run(
      next.name,
      next.type,
      next.version,
      next.updatedAt,
      next.isActive,
      next.content,
      next.css,
      stringifyJsonSafe(next.variables, DEFAULT_TEMPLATE_VARIABLES),
      templateId
    );

  const updated = getTemplateByIdFromDb(templateId);
  if (!updated) {
    throw new ApiError(500, 'Не удалось обновить шаблон.');
  }

  return updated;
};

const deleteTemplateByIdInDb = (templateId) => {
  const existing = getTemplateByIdFromDb(templateId);
  if (!existing) {
    throw new ApiError(404, 'Шаблон не найден.');
  }

  getDb().prepare('DELETE FROM templates WHERE id = ?').run(templateId);
};

const seedInvoicesIfNeeded = (sourceInvoices) => {
  const row = getDb().prepare('SELECT COUNT(*) AS count FROM invoices').get();
  const count = Number(row?.count || 0);

  if (count > 0 || !Array.isArray(sourceInvoices)) {
    return;
  }

  const insertInvoiceStatement = getDb().prepare(
    `INSERT INTO invoices (id, sort_order, number, date, payment_due_date, amount, currency, status, commission_percent, vat_rate, vat_mode, supplier_profile_id, supplier_bank_account_json, items_json, counterparty_id)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const total = sourceInvoices.length;
  sourceInvoices.forEach((invoice, index) => {
    const normalizedId = isNonEmptyString(invoice?.id) ? invoice.id : `inv-${Date.now()}-${index}`;
    const normalizedItems = normalizeInvoiceItems(invoice?.items);
    const calculatedAmount = normalizedItems.reduce(
      (sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0),
      0
    );
    insertInvoiceStatement.run(
      normalizedId,
      total - index,
      isNonEmptyString(invoice?.number) ? invoice.number : normalizedId,
      isNonEmptyString(invoice?.date) ? invoice.date : formatDate(),
      isNonEmptyString(invoice?.paymentDueDate) ? invoice.paymentDueDate : null,
      toNonNegativeNumber(invoice?.amount, calculatedAmount),
      toCurrency(invoice?.currency),
      toInvoiceStatus(invoice?.status),
      toMarkupPercent(invoice?.commissionPercent),
      toVatRate(invoice?.vatRate),
      toVatMode(invoice?.vatMode),
      isNonEmptyString(invoice?.supplierProfileId) ? invoice.supplierProfileId : null,
      stringifyJsonSafe(toSupplierBankAccount(invoice?.supplierBankAccount) || null, null),
      stringifyJsonSafe(normalizedItems, []),
      isNonEmptyString(invoice?.counterpartyId) ? invoice.counterpartyId : null
    );
  });
};

const seedCounterpartiesIfNeeded = (sourceCounterparties) => {
  const row = getDb().prepare('SELECT COUNT(*) AS count FROM counterparties').get();
  const count = Number(row?.count || 0);

  if (count > 0 || !Array.isArray(sourceCounterparties)) {
    return;
  }

  const insertCounterpartyStatement = getDb().prepare(
    `INSERT INTO counterparties (
       id,
       sort_order,
       name,
       inn,
       address,
       contact_person,
       email,
       phone,
       legal_type,
       director_name,
       ogrn,
       kpp,
       ogrnip,
       passport_series,
       passport_number,
       passport_issued_by,
       passport_issued_date,
       passport_department_code,
       registration_address,
       residence_address,
       bank_name,
       checking_account,
       correspondent_account,
       bik,
       bank_accounts_json
     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const total = sourceCounterparties.length;
  sourceCounterparties.forEach((counterparty, index) => {
    const normalizedId = isNonEmptyString(counterparty?.id) ? counterparty.id : `cp-${Date.now()}-${index}`;
    const bankAccounts = normalizeBankAccounts(counterparty?.bankAccounts, counterparty);
    const primaryBankAccount = getPrimaryBankAccount(bankAccounts, counterparty);
    insertCounterpartyStatement.run(
      normalizedId,
      total - index,
      isNonEmptyString(counterparty?.name) ? counterparty.name : normalizedId,
      toTrimmedString(counterparty?.inn),
      toTrimmedString(counterparty?.address),
      toTrimmedString(counterparty?.contactPerson),
      toTrimmedString(counterparty?.email),
      toTrimmedString(counterparty?.phone),
      toCounterpartyType(counterparty?.legalType, counterparty?.name),
      toTrimmedString(counterparty?.directorName),
      toTrimmedString(counterparty?.ogrn),
      toTrimmedString(counterparty?.kpp),
      toTrimmedString(counterparty?.ogrnip),
      toTrimmedString(counterparty?.passportSeries),
      toTrimmedString(counterparty?.passportNumber),
      toTrimmedString(counterparty?.passportIssuedBy),
      toTrimmedString(counterparty?.passportIssuedDate),
      toTrimmedString(counterparty?.passportDepartmentCode),
      toTrimmedString(counterparty?.registrationAddress),
      toTrimmedString(counterparty?.residenceAddress),
      primaryBankAccount.bankName,
      primaryBankAccount.checkingAccount,
      primaryBankAccount.correspondentAccount,
      primaryBankAccount.bik,
      stringifyJsonSafe(bankAccounts, [])
    );
  });
};

const seedTemplatesIfNeeded = (sourceTemplates) => {
  const row = getDb().prepare('SELECT COUNT(*) AS count FROM templates').get();
  const count = Number(row?.count || 0);

  if (count > 0 || !Array.isArray(sourceTemplates)) {
    return;
  }

  const insertTemplateStatement = getDb().prepare(
    `INSERT INTO templates (id, sort_order, name, type, version, updated_at, is_active, content_html, css_text, variables_json)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const total = sourceTemplates.length;
  sourceTemplates.forEach((template, index) => {
    const normalizedId = isNonEmptyString(template?.id) ? template.id : `tpl-${Date.now()}-${index}`;
    insertTemplateStatement.run(
      normalizedId,
      total - index,
      isNonEmptyString(template?.name) ? template.name : normalizedId,
      isNonEmptyString(template?.type) ? template.type : CONTRACT_TYPE.SERVICE,
      isNonEmptyString(template?.version) ? template.version : '1.0',
      isNonEmptyString(template?.updatedAt) ? template.updatedAt : formatDate(),
      template?.isActive === false ? 0 : 1,
      normalizeTemplateContent(template?.content),
      normalizeTemplateCss(template?.css),
      stringifyJsonSafe(normalizeTemplateVariables(template?.variables), DEFAULT_TEMPLATE_VARIABLES)
    );
  });
};

const seedSettingsIfNeeded = (sourceSettings) => {
  const row = getDb().prepare('SELECT COUNT(*) AS count FROM app_settings').get();
  const count = Number(row?.count || 0);

  if (count > 0) {
    return;
  }

  const mergedSettings =
    sourceSettings && typeof sourceSettings === 'object'
      ? { ...deepClone(DEFAULT_DATA.settings), ...sourceSettings }
      : deepClone(DEFAULT_DATA.settings);

  setSettingsInDb(mergedSettings);
};

const seedContractsIfNeeded = (sourceContracts) => {
  const row = getDb().prepare('SELECT COUNT(*) AS count FROM contracts').get();
  const count = Number(row?.count || 0);

  if (count > 0 || !Array.isArray(sourceContracts)) {
    return;
  }

  const insertContractStatement = getDb().prepare(
    `INSERT INTO contracts (
       id,
       sort_order,
       number,
       title,
       type,
       counterparty_json,
       status,
       created_at,
       amount,
       supplier_profile_id,
       invoice_id,
       payment_terms,
       include_delivery,
       delivery_date,
       vat_rate,
       vat_mode,
       markup_percent,
       markup_mode,
       markup_calc_mode,
       template_id,
       template_name,
       template_version,
       contract_data_json,
       html_snapshot,
       snapshot_css
     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const total = sourceContracts.length;
  sourceContracts.forEach((contract, index) => {
    const normalizedId = isNonEmptyString(contract?.id) ? contract.id : `c-${Date.now()}-${index}`;
    insertContractStatement.run(
      normalizedId,
      total - index,
      isNonEmptyString(contract?.number) ? contract.number : `Д-${new Date().getFullYear()}-001`,
      isNonEmptyString(contract?.title) ? contract.title : 'Договор',
      isNonEmptyString(contract?.type) ? contract.type : CONTRACT_TYPE.SERVICE,
      stringifyJsonSafe(contract?.counterparty && typeof contract.counterparty === 'object' ? contract.counterparty : {}, {}),
      isNonEmptyString(contract?.status) ? contract.status : CONTRACT_STATUS.DRAFT,
      isNonEmptyString(contract?.createdAt) ? contract.createdAt : formatDate(),
      contract?.amount == null ? null : Number(contract.amount),
      isNonEmptyString(contract?.supplierProfileId) ? contract.supplierProfileId : null,
      isNonEmptyString(contract?.invoiceId) ? contract.invoiceId : null,
      contract?.paymentTerms == null ? null : Number(contract.paymentTerms),
      contract?.includeDelivery ? 1 : 0,
      contract?.deliveryDate == null ? null : contract.deliveryDate,
      toVatRate(contract?.vatRate),
      toVatMode(contract?.vatMode),
      toMarkupPercent(contract?.markupPercent),
      toMarkupMode(contract?.markupMode),
      toMarkupCalcMode(contract?.markupCalcMode),
      toTrimmedString(contract?.templateId),
      toTrimmedString(contract?.templateName),
      toTrimmedString(contract?.templateVersion),
      stringifyJsonSafe(contract?.contractData, {}),
      isNonEmptyString(contract?.htmlSnapshot) ? contract.htmlSnapshot : '',
      isNonEmptyString(contract?.snapshotCss) ? contract.snapshotCss : ''
    );
  });
};

const ensureColumnExists = (tableName, columnName, columnDefinition) => {
  const columns = getDb().prepare(`PRAGMA table_info(${tableName})`).all();
  const hasColumn = columns.some((column) => column.name === columnName);

  if (hasColumn) {
    return;
  }

  getDb().exec(`ALTER TABLE ${tableName} ADD COLUMN ${columnDefinition}`);
};

const ensureContractsSchema = () => {
  ensureColumnExists('contracts', 'supplier_profile_id', 'supplier_profile_id TEXT');
  ensureColumnExists('contracts', 'vat_rate', "vat_rate TEXT NOT NULL DEFAULT 'none'");
  ensureColumnExists('contracts', 'vat_mode', "vat_mode TEXT NOT NULL DEFAULT 'included'");
  ensureColumnExists('contracts', 'markup_percent', "markup_percent REAL NOT NULL DEFAULT 6");
  ensureColumnExists('contracts', 'markup_mode', "markup_mode TEXT NOT NULL DEFAULT 'per_item'");
  ensureColumnExists('contracts', 'markup_calc_mode', "markup_calc_mode TEXT NOT NULL DEFAULT 'simple'");
  ensureColumnExists('contracts', 'template_id', "template_id TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('contracts', 'template_name', "template_name TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('contracts', 'template_version', "template_version TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('contracts', 'contract_data_json', "contract_data_json TEXT NOT NULL DEFAULT '{}'");
  ensureColumnExists('contracts', 'html_snapshot', "html_snapshot TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('contracts', 'snapshot_css', "snapshot_css TEXT NOT NULL DEFAULT ''");
};

const ensureInvoicesSchema = () => {
  ensureColumnExists('invoices', 'counterparty_id', 'counterparty_id TEXT');
  ensureColumnExists('invoices', 'commission_percent', 'commission_percent REAL NOT NULL DEFAULT 6');
  ensureColumnExists('invoices', 'vat_rate', "vat_rate TEXT NOT NULL DEFAULT 'none'");
  ensureColumnExists('invoices', 'vat_mode', "vat_mode TEXT NOT NULL DEFAULT 'included'");
  ensureColumnExists('invoices', 'supplier_profile_id', 'supplier_profile_id TEXT');
  ensureColumnExists('invoices', 'supplier_bank_account_json', 'supplier_bank_account_json TEXT');
  ensureColumnExists('invoices', 'payment_due_date', 'payment_due_date TEXT');
};

const ensureCounterpartiesSchema = () => {
  ensureColumnExists('counterparties', 'legal_type', "legal_type TEXT NOT NULL DEFAULT 'ooo'");
  ensureColumnExists('counterparties', 'director_name', "director_name TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'ogrn', "ogrn TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'kpp', "kpp TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'ogrnip', "ogrnip TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'phone', "phone TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'passport_series', "passport_series TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'passport_number', "passport_number TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'passport_issued_by', "passport_issued_by TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'passport_issued_date', "passport_issued_date TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'passport_department_code', "passport_department_code TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'registration_address', "registration_address TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'residence_address', "residence_address TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'bank_name', "bank_name TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'checking_account', "checking_account TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'correspondent_account', "correspondent_account TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'bik', "bik TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('counterparties', 'bank_accounts_json', "bank_accounts_json TEXT NOT NULL DEFAULT '[]'");
};

const ensureTemplatesSchema = () => {
  ensureColumnExists('templates', 'is_active', 'is_active INTEGER NOT NULL DEFAULT 1');
  ensureColumnExists('templates', 'content_html', "content_html TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('templates', 'css_text', "css_text TEXT NOT NULL DEFAULT ''");
  ensureColumnExists('templates', 'variables_json', "variables_json TEXT NOT NULL DEFAULT '[]'");
};

const backfillTemplatesIfNeeded = () => {
  const rows = getDb()
    .prepare('SELECT id, content_html, css_text, variables_json, is_active FROM templates')
    .all();

  const statement = getDb().prepare(
    `UPDATE templates
     SET content_html = ?, css_text = ?, variables_json = ?, is_active = ?
     WHERE id = ?`
  );

  rows.forEach((row) => {
    const content = normalizeTemplateContent(row.content_html);
    const css = normalizeTemplateCss(row.css_text);
    const variables = normalizeTemplateVariables(parseJsonSafe(row.variables_json, DEFAULT_TEMPLATE_VARIABLES));
    const variablesJson = stringifyJsonSafe(variables, DEFAULT_TEMPLATE_VARIABLES);
    const isActive = row.is_active === 0 ? 0 : 1;

    if (
      content !== row.content_html ||
      css !== row.css_text ||
      variablesJson !== row.variables_json ||
      isActive !== row.is_active
    ) {
      statement.run(content, css, variablesJson, isActive, row.id);
    }
  });
};

const ensureSupplyWithVatTemplate = () => {
  const existing = getDb()
    .prepare('SELECT id FROM templates WHERE name = ? LIMIT 1')
    .get('Договор поставки с НДС');
  if (existing) {
    return;
  }

  insertTemplateToDb({
    id: 'tpl-supply-vat-2026',
    name: 'Договор поставки с НДС',
    type: CONTRACT_TYPE.SUPPLY,
    version: '2.2',
    updatedAt: formatDate(),
    isActive: true,
    content: SUPPLY_WITH_VAT_TEMPLATE_CONTENT,
    css: DEFAULT_TEMPLATE_CSS,
    variables: DEFAULT_TEMPLATE_VARIABLES,
  });
};

const ensureSupplyLegalEntitiesTemplate = () => {
  const seededTemplate = getTemplateByIdFromDb(SUPPLY_LEGAL_ENTITIES_TEMPLATE_ID);
  if (seededTemplate) {
    updateTemplateByIdInDb(seededTemplate.id, {
      name: SUPPLY_LEGAL_ENTITIES_TEMPLATE_NAME,
      type: CONTRACT_TYPE.SUPPLY,
      version: '1.0',
      content: SUPPLY_LEGAL_ENTITIES_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    });
    return;
  }

  const existingByName = getDb()
    .prepare('SELECT id FROM templates WHERE name = ? LIMIT 1')
    .get(SUPPLY_LEGAL_ENTITIES_TEMPLATE_NAME);
  if (existingByName) {
    return;
  }

  insertTemplateToDb({
    id: SUPPLY_LEGAL_ENTITIES_TEMPLATE_ID,
    name: SUPPLY_LEGAL_ENTITIES_TEMPLATE_NAME,
    type: CONTRACT_TYPE.SUPPLY,
    version: '1.0',
    updatedAt: formatDate(),
    isActive: true,
    content: SUPPLY_LEGAL_ENTITIES_TEMPLATE_CONTENT,
    css: DEFAULT_TEMPLATE_CSS,
    variables: DEFAULT_TEMPLATE_VARIABLES,
  });
};

const ensureGoodsSaleExtendedConfidentialityTemplate = () => {
  const seededIds = ['tpl-goods-sale-extended-conf-2026', 't5'];
  const seededTemplate = seededIds.map((id) => getTemplateByIdFromDb(id)).find(Boolean);
  if (seededTemplate) {
    updateTemplateByIdInDb(seededTemplate.id, {
      name: 'Договор купли-продажи товара (расширенный, конфиденциальность)',
      type: CONTRACT_TYPE.SUPPLY,
      version: '1.3',
      content: GOODS_SALE_EXTENDED_CONFIDENTIALITY_TEMPLATE_CONTENT,
      css: DEFAULT_TEMPLATE_CSS,
      variables: DEFAULT_TEMPLATE_VARIABLES,
    });
    return;
  }

  const existingByName = getDb()
    .prepare('SELECT id FROM templates WHERE name = ? LIMIT 1')
    .get('Договор купли-продажи товара (расширенный, конфиденциальность)');
  if (existingByName) {
    return;
  }

  insertTemplateToDb({
    id: 'tpl-goods-sale-extended-conf-2026',
    name: 'Договор купли-продажи товара (расширенный, конфиденциальность)',
    type: CONTRACT_TYPE.SUPPLY,
    version: '1.3',
    updatedAt: formatDate(),
    isActive: true,
    content: GOODS_SALE_EXTENDED_CONFIDENTIALITY_TEMPLATE_CONTENT,
    css: DEFAULT_TEMPLATE_CSS,
    variables: DEFAULT_TEMPLATE_VARIABLES,
  });
};

const backfillBrokenContractSnapshotsIfNeeded = () => {
  const brokenRows = getDb()
    .prepare("SELECT id FROM contracts WHERE html_snapshot LIKE '%{{%' OR html_snapshot LIKE '%}}%'")
    .all();

  brokenRows.forEach((row) => {
    const contract = getContractByIdFromDb(row.id);
    if (!contract) {
      return;
    }

    try {
      const refreshed = buildContractSnapshotPayload({
        contract,
        counterparty: contract.counterparty,
        invoice: contract.invoiceId ? getInvoiceByIdFromDb(contract.invoiceId) : null,
        templateId: contract.templateId,
      });
      saveContractByIdToDb(contract.id, refreshed);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`Contract snapshot backfill skipped for ${row.id}: ${message}`);
    }
  });
};

const backfillGoodsSaleContractSnapshotsIfNeeded = () => {
  const rows = getDb()
    .prepare(
      `SELECT id
       FROM contracts
       WHERE template_name = ?
          OR template_id = ?
          OR template_id = ?`
    )
    .all(
      'Договор купли-продажи товара (расширенный, конфиденциальность)',
      't5',
      'tpl-goods-sale-extended-conf-2026'
    );

  rows.forEach((row) => {
    const contract = getContractByIdFromDb(row.id);
    if (!contract) {
      return;
    }

    try {
      const refreshed = buildContractSnapshotPayload({
        contract,
        counterparty: contract.counterparty,
        invoice: contract.invoiceId ? getInvoiceByIdFromDb(contract.invoiceId) : null,
        templateId: contract.templateId,
      });
      saveContractByIdToDb(contract.id, refreshed);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`Goods-sale contract snapshot backfill skipped for ${row.id}: ${message}`);
    }
  });
};

const backfillCounterpartyBankAccountsIfNeeded = () => {
  const rows = getDb()
    .prepare('SELECT id, bank_name, checking_account, correspondent_account, bik, bank_accounts_json FROM counterparties')
    .all();

  const statement = getDb().prepare(
    `UPDATE counterparties
     SET bank_name = ?, checking_account = ?, correspondent_account = ?, bik = ?, bank_accounts_json = ?
     WHERE id = ?`
  );

  rows.forEach((row) => {
    const bankAccounts = normalizeBankAccounts(parseJsonSafe(row.bank_accounts_json, []), {
      bankName: row.bank_name,
      checkingAccount: row.checking_account,
      correspondentAccount: row.correspondent_account,
      bik: row.bik,
    });
    const primaryBankAccount = getPrimaryBankAccount(bankAccounts);
    const nextBankAccountsJson = stringifyJsonSafe(bankAccounts, []);
    const currentBankName = toTrimmedString(row.bank_name);
    const currentCheckingAccount = toTrimmedString(row.checking_account);
    const currentCorrespondentAccount = toTrimmedString(row.correspondent_account);
    const currentBik = toTrimmedString(row.bik);

    if (
      currentBankName !== primaryBankAccount.bankName ||
      currentCheckingAccount !== primaryBankAccount.checkingAccount ||
      currentCorrespondentAccount !== primaryBankAccount.correspondentAccount ||
      currentBik !== primaryBankAccount.bik ||
      row.bank_accounts_json !== nextBankAccountsJson
    ) {
      statement.run(
        primaryBankAccount.bankName,
        primaryBankAccount.checkingAccount,
        primaryBankAccount.correspondentAccount,
        primaryBankAccount.bik,
        nextBankAccountsJson,
        row.id
      );
    }
  });
};

const initDatabase = async () => {
  const sourceData = await readData();
  let dbFileExists = true;
  try {
    await fs.access(DB_FILE);
  } catch {
    dbFileExists = false;
  }

  const database = new DatabaseSync(DB_FILE);
  database.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS counterparties (
      id TEXT PRIMARY KEY,
      sort_order INTEGER NOT NULL,
      name TEXT NOT NULL,
      inn TEXT NOT NULL,
      address TEXT NOT NULL,
      contact_person TEXT NOT NULL,
      email TEXT NOT NULL,
      phone TEXT NOT NULL DEFAULT '',
      legal_type TEXT NOT NULL DEFAULT 'ooo',
      director_name TEXT NOT NULL DEFAULT '',
      ogrn TEXT NOT NULL DEFAULT '',
      kpp TEXT NOT NULL DEFAULT '',
      ogrnip TEXT NOT NULL DEFAULT '',
      passport_series TEXT NOT NULL DEFAULT '',
      passport_number TEXT NOT NULL DEFAULT '',
      passport_issued_by TEXT NOT NULL DEFAULT '',
      passport_issued_date TEXT NOT NULL DEFAULT '',
      passport_department_code TEXT NOT NULL DEFAULT '',
      registration_address TEXT NOT NULL DEFAULT '',
      residence_address TEXT NOT NULL DEFAULT '',
      bank_name TEXT NOT NULL DEFAULT '',
      checking_account TEXT NOT NULL DEFAULT '',
      correspondent_account TEXT NOT NULL DEFAULT '',
      bik TEXT NOT NULL DEFAULT '',
      bank_accounts_json TEXT NOT NULL DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS templates (
      id TEXT PRIMARY KEY,
      sort_order INTEGER NOT NULL,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      version TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      content_html TEXT NOT NULL DEFAULT '',
      css_text TEXT NOT NULL DEFAULT '',
      variables_json TEXT NOT NULL DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS app_settings (
      id INTEGER PRIMARY KEY CHECK(id = 1),
      payload_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS invoices (
      id TEXT PRIMARY KEY,
      sort_order INTEGER NOT NULL,
      number TEXT NOT NULL,
      date TEXT NOT NULL,
      payment_due_date TEXT,
      amount REAL NOT NULL DEFAULT 0,
      currency TEXT NOT NULL DEFAULT 'RUB',
      status TEXT NOT NULL,
      commission_percent REAL NOT NULL DEFAULT 6,
      vat_rate TEXT NOT NULL DEFAULT 'none',
      vat_mode TEXT NOT NULL DEFAULT 'included',
      supplier_profile_id TEXT,
      supplier_bank_account_json TEXT,
      items_json TEXT NOT NULL DEFAULT '[]',
      counterparty_id TEXT
    );

    CREATE TABLE IF NOT EXISTS contracts (
      id TEXT PRIMARY KEY,
      sort_order INTEGER NOT NULL,
      number TEXT NOT NULL,
      title TEXT NOT NULL,
      type TEXT NOT NULL,
      counterparty_json TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      amount REAL,
      supplier_profile_id TEXT,
      invoice_id TEXT,
      payment_terms INTEGER,
      include_delivery INTEGER NOT NULL DEFAULT 0,
      delivery_date TEXT,
      vat_rate TEXT NOT NULL DEFAULT 'none',
      vat_mode TEXT NOT NULL DEFAULT 'included',
      markup_percent REAL NOT NULL DEFAULT 6,
      markup_mode TEXT NOT NULL DEFAULT 'per_item',
      markup_calc_mode TEXT NOT NULL DEFAULT 'simple',
      template_id TEXT NOT NULL DEFAULT '',
      template_name TEXT NOT NULL DEFAULT '',
      template_version TEXT NOT NULL DEFAULT '',
      contract_data_json TEXT NOT NULL DEFAULT '{}',
      html_snapshot TEXT NOT NULL DEFAULT '',
      snapshot_css TEXT NOT NULL DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_counterparties_sort_order ON counterparties(sort_order DESC);
    CREATE INDEX IF NOT EXISTS idx_templates_sort_order ON templates(sort_order DESC);
    CREATE INDEX IF NOT EXISTS idx_invoices_sort_order ON invoices(sort_order DESC);
    CREATE INDEX IF NOT EXISTS idx_contracts_sort_order ON contracts(sort_order DESC);
    CREATE INDEX IF NOT EXISTS idx_contracts_invoice_id ON contracts(invoice_id);
    CREATE INDEX IF NOT EXISTS idx_contracts_template_id ON contracts(template_id);
  `);

  db = database;
  ensureCounterpartiesSchema();
  ensureContractsSchema();
  ensureInvoicesSchema();
  ensureTemplatesSchema();
  backfillTemplatesIfNeeded();
  ensureSupplyWithVatTemplate();
  ensureSupplyLegalEntitiesTemplate();
  ensureGoodsSaleExtendedConfidentialityTemplate();
  backfillBrokenContractSnapshotsIfNeeded();
  backfillGoodsSaleContractSnapshotsIfNeeded();
  backfillCounterpartyBankAccountsIfNeeded();
  getDb().exec('CREATE INDEX IF NOT EXISTS idx_invoices_counterparty_id ON invoices(counterparty_id)');

  const seedMarkerRow = getDb().prepare('SELECT value FROM app_meta WHERE key = ?').get(SEED_MARKER_KEY);
  const hasSeedMarker = Boolean(seedMarkerRow);

  if (!hasSeedMarker) {
    if (!dbFileExists) {
      seedCounterpartiesIfNeeded(sourceData.counterparties);
      seedTemplatesIfNeeded(sourceData.templates);
      seedSettingsIfNeeded(sourceData.settings);
      seedInvoicesIfNeeded(sourceData.invoices);
      seedContractsIfNeeded(sourceData.contracts);
    }

    getDb()
      .prepare(
        `INSERT INTO app_meta (key, value)
         VALUES (?, ?)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value`
      )
      .run(SEED_MARKER_KEY, new Date().toISOString());
  }
};

app.get(
  '/api/health',
  asyncHandler(async (_req, res) => {
    const contracts = listContractsFromDb();
    const invoices = listInvoicesFromDb();
    const stats = buildDashboardStats(contracts, invoices);

    res.set(JSON_HEADERS).status(200).send(
      JSON.stringify({
        status: 'ok',
        timestamp: new Date().toISOString(),
        contracts: stats.totalContracts,
      })
    );
  })
);

app.get(
  '/api/bootstrap',
  asyncHandler(async (_req, res) => {
    const counterparties = listCounterpartiesFromDb();
    const templates = listTemplatesFromDb();
    const templateVariables = deepClone(DEFAULT_TEMPLATE_VARIABLES);
    const settings = getSettingsFromDb();
    const contracts = listContractsFromDb();
    const invoices = listInvoicesFromDb();
    const stats = buildDashboardStats(contracts, invoices);
    res.status(200).json({
      contracts,
      counterparties,
      invoices,
      templates,
      templateVariables,
      settings,
      stats,
    });
  })
);

app.get(
  '/api/dashboard',
  asyncHandler(async (_req, res) => {
    const contracts = listContractsFromDb();
    const invoices = listInvoicesFromDb();
    res.status(200).json(buildDashboardStats(contracts, invoices));
  })
);

app.get(
  '/api/contracts',
  asyncHandler(async (req, res) => {
    const limit = toPositiveInteger(req.query.limit, 0);
    const contracts = listContractsFromDb(limit);
    res.status(200).json(contracts);
  })
);

app.post(
  '/api/contracts/preview',
  asyncHandler(async (req, res) => {
    const {
      type,
      templateId,
      number,
      amount,
      paymentTerms,
      includeDelivery = true,
      deliveryDate = null,
      vatRate,
      vatMode,
      markupPercent,
      markupMode,
      markupCalcMode,
      contractData,
      counterparty: rawCounterparty,
      invoice: rawInvoice,
    } = req.body || {};

    if (!isNonEmptyString(type)) {
      throw new ApiError(400, 'Поле "type" обязательно.');
    }

    const template = getTemplateForContract({ templateId, type });
    const settings = getSettingsFromDb();

    const counterparty =
      rawCounterparty && typeof rawCounterparty === 'object'
        ? {
            id: toTrimmedString(rawCounterparty.id) || 'preview-counterparty',
            legalType: toCounterpartyType(rawCounterparty.legalType, rawCounterparty.name),
            name: toTrimmedString(rawCounterparty.name),
            inn: toTrimmedString(rawCounterparty.inn),
            address: toTrimmedString(rawCounterparty.address),
            contactPerson: toTrimmedString(rawCounterparty.contactPerson),
            email: toTrimmedString(rawCounterparty.email),
            phone: toTrimmedString(rawCounterparty.phone),
            directorName: toTrimmedString(rawCounterparty.directorName),
            ogrn: toTrimmedString(rawCounterparty.ogrn),
            kpp: toTrimmedString(rawCounterparty.kpp),
            ogrnip: toTrimmedString(rawCounterparty.ogrnip),
            passportSeries: toTrimmedString(rawCounterparty.passportSeries),
            passportNumber: toTrimmedString(rawCounterparty.passportNumber),
            passportIssuedBy: toTrimmedString(rawCounterparty.passportIssuedBy),
            passportIssuedDate: toTrimmedString(rawCounterparty.passportIssuedDate),
            passportDepartmentCode: toTrimmedString(rawCounterparty.passportDepartmentCode),
            registrationAddress: toTrimmedString(rawCounterparty.registrationAddress),
            residenceAddress: toTrimmedString(rawCounterparty.residenceAddress),
            bankAccounts: normalizeBankAccounts(rawCounterparty.bankAccounts, rawCounterparty),
            bankName: toTrimmedString(rawCounterparty.bankName),
            checkingAccount: toTrimmedString(rawCounterparty.checkingAccount),
            correspondentAccount: toTrimmedString(rawCounterparty.correspondentAccount),
            bik: toTrimmedString(rawCounterparty.bik),
          }
        : null;

    const previewInvoice =
      rawInvoice && typeof rawInvoice === 'object'
        ? {
            id: toTrimmedString(rawInvoice.id) || 'preview-invoice',
            number: toTrimmedString(rawInvoice.number),
            date: toTrimmedString(rawInvoice.date),
            paymentDueDate: toTrimmedString(rawInvoice.paymentDueDate) || undefined,
            amount: toNonNegativeNumber(rawInvoice.amount, 0),
            currency: toCurrency(rawInvoice.currency),
            status: toInvoiceStatus(rawInvoice.status),
            items: normalizeInvoiceItems(rawInvoice.items),
            commissionPercent: toMarkupPercent(rawInvoice.commissionPercent),
            vatRate: toVatRate(rawInvoice.vatRate),
            vatMode: toVatMode(rawInvoice.vatMode),
            supplierProfileId: toTrimmedString(rawInvoice.supplierProfileId) || undefined,
            supplierBankAccount: toSupplierBankAccount(rawInvoice.supplierBankAccount),
            counterpartyId: toTrimmedString(rawInvoice.counterpartyId) || undefined,
          }
        : null;

    const normalizedVatRate = previewInvoice ? toVatRate(previewInvoice.vatRate) : toVatRate(vatRate);
    const normalizedVatMode = previewInvoice ? toVatMode(previewInvoice.vatMode) : toVatMode(vatMode);
    const normalizedMarkupPercent = previewInvoice ? toMarkupPercent(previewInvoice.commissionPercent) : toMarkupPercent(markupPercent);
    const normalizedMarkupMode = toMarkupMode(markupMode);
    const normalizedMarkupCalcMode = toMarkupCalcMode(markupCalcMode);
    const fallbackAmount = previewInvoice ? Number(previewInvoice.amount || 0) : 0;
    const normalizedAmount = toNonNegativeNumber(amount, fallbackAmount);

    const previewContract = {
      id: 'preview-contract',
      number: isNonEmptyString(number) ? number.trim() : 'Д-ПРЕДПРОСМОТР',
      title: buildContractTitle(type, counterparty),
      type,
      counterparty: counterparty || {},
      status: CONTRACT_STATUS.DRAFT,
      createdAt: formatDate(),
      amount: previewInvoice || Number.isFinite(Number(amount)) ? normalizedAmount : undefined,
      supplierProfileId: resolveSupplierProfileIdForContract(previewInvoice),
      invoiceId: undefined,
      paymentTerms: toPositiveInteger(paymentTerms, 10),
      includeDelivery: Boolean(includeDelivery),
      deliveryDate: isNonEmptyString(deliveryDate) ? deliveryDate : null,
      vatRate: normalizedVatRate,
      vatMode: normalizedVatMode,
      markupPercent: normalizedMarkupPercent,
      markupMode: normalizedMarkupMode,
      markupCalcMode: normalizedMarkupCalcMode,
      contractData: contractData && typeof contractData === 'object' ? contractData : {},
    };
    assertSupplyLegalEntitiesTemplateCompatibility({
      template,
      counterparty,
      settings,
      supplierProfileId: previewInvoice?.supplierProfileId || previewContract?.supplierProfileId,
    });

    const templateContext = buildContractTemplateContext({
      contract: previewContract,
      counterparty,
      invoice: previewInvoice,
      settings,
    });
    const html = renderTemplateContent(normalizeTemplateContent(template.content), templateContext);
    if (!isNonEmptyString(html)) {
      throw new ApiError(500, 'Не удалось сформировать live-preview шаблона.');
    }

    res.status(200).json({
      html,
      css: normalizeTemplateCss(template.css),
      templateId: template.id,
      templateName: template.name,
      templateVersion: template.version,
    });
  })
);

app.post(
  '/api/contracts',
  asyncHandler(async (req, res) => {
    const {
      type,
      counterpartyId,
      invoiceId,
      amount,
      paymentTerms,
      includeDelivery = true,
      deliveryDate = null,
      number,
      vatRate,
      vatMode,
      markupPercent,
      markupMode,
      markupCalcMode,
      templateId,
      contractData,
    } = req.body || {};

    if (!isNonEmptyString(type)) {
      throw new ApiError(400, 'Поле "type" обязательно.');
    }

    if (!isNonEmptyString(counterpartyId)) {
      throw new ApiError(400, 'Поле "counterpartyId" обязательно.');
    }

    const contract = await withDataLock(async () => {
      const counterparty = getCounterpartyByIdFromDb(counterpartyId);
      if (!counterparty) {
        throw new ApiError(404, 'Контрагент не найден.');
      }

      let invoice = null;
      if (isNonEmptyString(invoiceId)) {
        invoice = getInvoiceByIdFromDb(invoiceId);
        if (!invoice) {
          throw new ApiError(404, 'Счёт не найден.');
        }
      }

      const normalizedVatRate = invoice ? toVatRate(invoice.vatRate) : toVatRate(vatRate);
      const normalizedVatMode = invoice ? toVatMode(invoice.vatMode) : toVatMode(vatMode);
      const normalizedMarkupPercent = invoice
        ? toMarkupPercent(invoice.commissionPercent)
        : toMarkupPercent(markupPercent);
      const normalizedMarkupMode = toMarkupMode(markupMode);
      const normalizedMarkupCalcMode = toMarkupCalcMode(markupCalcMode);
      const fallbackAmount = invoice ? Number(invoice.amount || 0) : 0;
      const normalizedAmount = toNonNegativeNumber(amount, fallbackAmount);
      const template = getTemplateForContract({ templateId, type });
      const settings = getSettingsFromDb();

      const existingContracts = listContractsFromDb();
      const contractNumber = isNonEmptyString(number) ? number.trim() : nextContractNumber(existingContracts);
      const nextContract = {
        id: `c-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        number: contractNumber,
        title: buildContractTitle(type, counterparty),
        type,
        counterparty,
        status: CONTRACT_STATUS.DRAFT,
        createdAt: formatDate(),
        amount: invoice || Number.isFinite(Number(amount)) ? normalizedAmount : undefined,
        supplierProfileId: resolveSupplierProfileIdForContract(invoice),
        invoiceId: invoice ? invoice.id : undefined,
        paymentTerms: toPositiveInteger(paymentTerms, 10),
        includeDelivery: Boolean(includeDelivery),
        deliveryDate: isNonEmptyString(deliveryDate) ? deliveryDate : null,
        vatRate: normalizedVatRate,
        vatMode: normalizedVatMode,
        markupPercent: normalizedMarkupPercent,
        markupMode: normalizedMarkupMode,
        markupCalcMode: normalizedMarkupCalcMode,
        contractData: contractData && typeof contractData === 'object' ? contractData : {},
      };
      assertSupplyLegalEntitiesTemplateCompatibility({
        template,
        counterparty,
        settings,
        supplierProfileId: invoice?.supplierProfileId || nextContract?.supplierProfileId,
      });

      const templateContext = buildContractTemplateContext({
        contract: nextContract,
        counterparty,
        invoice,
        settings,
      });
      const htmlSnapshot = renderTemplateContent(normalizeTemplateContent(template.content), templateContext);
      if (!isNonEmptyString(htmlSnapshot)) {
        throw new ApiError(500, 'Не удалось сформировать HTML-слепок договора.');
      }

      nextContract.templateId = template.id;
      nextContract.templateName = template.name;
      nextContract.templateVersion = template.version;
      nextContract.contractData = templateContext;
      nextContract.htmlSnapshot = htmlSnapshot;
      nextContract.snapshotCss = normalizeTemplateCss(template.css);

      insertContractToDb(nextContract);
      return nextContract;
    });

    res.status(201).json(contract);
  })
);

app.put(
  '/api/contracts/:id',
  asyncHandler(async (req, res) => {
    const contractId = toTrimmedString(req.params.id);
    if (!contractId) {
      throw new ApiError(400, 'Некорректный идентификатор договора.');
    }

    if (!req.body || typeof req.body !== 'object') {
      throw new ApiError(400, 'Тело запроса должно быть объектом.');
    }

    const updatedContract = await withDataLock(async () => updateContractByIdInDb(contractId, req.body));
    res.status(200).json(updatedContract);
  })
);

app.delete(
  '/api/contracts/:id',
  asyncHandler(async (req, res) => {
    const contractId = toTrimmedString(req.params.id);
    if (!contractId) {
      throw new ApiError(400, 'Некорректный идентификатор договора.');
    }

    await withDataLock(async () => deleteContractByIdInDb(contractId));
    res.status(204).end();
  })
);

app.get(
  '/api/counterparties',
  asyncHandler(async (_req, res) => {
    res.status(200).json(listCounterpartiesFromDb());
  })
);

app.get(
  '/api/counterparties/lookup',
  asyncHandler(async (req, res) => {
    const inn = toTrimmedString(req.query.inn);
    if (!isNonEmptyString(inn)) {
      throw new ApiError(400, 'Укажите ИНН для поиска.');
    }

    const counterparty = getCounterpartyByInnFromDb(inn);
    if (counterparty) {
      res.status(200).json({
        found: true,
        source: 'db',
        counterparty,
      });
      return;
    }

    res.status(200).json({
      found: false,
      source: 'none',
    });
  })
);

app.post(
  '/api/counterparties',
  asyncHandler(async (req, res) => {
    const {
      legalType,
      name,
      inn,
      address,
      contactPerson,
      email,
      phone,
      directorName,
      ogrn,
      kpp,
      ogrnip,
      passportSeries,
      passportNumber,
      passportIssuedBy,
      passportIssuedDate,
      passportDepartmentCode,
      registrationAddress,
      residenceAddress,
      bankName,
      checkingAccount,
      correspondentAccount,
      bik,
      bankAccounts,
    } = req.body || {};

    if (!isNonEmptyString(name)) {
      throw new ApiError(400, 'Поле "name" обязательно.');
    }

    if (!isNonEmptyString(inn) && toCounterpartyType(legalType, name) !== 'person') {
      throw new ApiError(400, 'Поле "inn" обязательно.');
    }

    const normalizedType = toCounterpartyType(legalType, name);
    if (!VALID_COUNTERPARTY_TYPES.has(normalizedType)) {
      throw new ApiError(400, 'Поле "legalType" должно быть ooo, ao, ip или person.');
    }

    if ((normalizedType === 'ooo' || normalizedType === 'ao') && !isNonEmptyString(directorName)) {
      throw new ApiError(400, 'Для ООО/АО укажите руководителя в поле "directorName".');
    }

    const counterparty = await withDataLock(async () => {
      const normalizedBankAccounts = normalizeBankAccounts(bankAccounts, {
        bankName,
        checkingAccount,
        correspondentAccount,
        bik,
      });
      const primaryBankAccount = getPrimaryBankAccount(normalizedBankAccounts);

      const nextCounterparty = {
        id: `cp-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        legalType: normalizedType,
        name: name.trim(),
        inn: isNonEmptyString(inn) ? inn.trim() : '',
        address:
          normalizedType === 'person'
            ? (isNonEmptyString(registrationAddress) ? registrationAddress.trim() : isNonEmptyString(address) ? address.trim() : '')
            : isNonEmptyString(address)
              ? address.trim()
              : '',
        contactPerson:
          normalizedType === 'person'
            ? (isNonEmptyString(contactPerson) ? contactPerson.trim() : name.trim())
            : isNonEmptyString(contactPerson)
              ? contactPerson.trim()
              : '',
        email: isNonEmptyString(email) ? email.trim() : '',
        phone: isNonEmptyString(phone) ? phone.trim() : '',
        directorName: isNonEmptyString(directorName) ? directorName.trim() : '',
        ogrn: isNonEmptyString(ogrn) ? ogrn.trim() : '',
        kpp: isNonEmptyString(kpp) ? kpp.trim() : '',
        ogrnip: isNonEmptyString(ogrnip) ? ogrnip.trim() : '',
        passportSeries: isNonEmptyString(passportSeries) ? passportSeries.trim() : '',
        passportNumber: isNonEmptyString(passportNumber) ? passportNumber.trim() : '',
        passportIssuedBy: isNonEmptyString(passportIssuedBy) ? passportIssuedBy.trim() : '',
        passportIssuedDate: isNonEmptyString(passportIssuedDate) ? passportIssuedDate.trim() : '',
        passportDepartmentCode: isNonEmptyString(passportDepartmentCode) ? passportDepartmentCode.trim() : '',
        registrationAddress: isNonEmptyString(registrationAddress) ? registrationAddress.trim() : '',
        residenceAddress: isNonEmptyString(residenceAddress) ? residenceAddress.trim() : '',
        bankAccounts: normalizedBankAccounts,
        bankName: primaryBankAccount.bankName,
        checkingAccount: primaryBankAccount.checkingAccount,
        correspondentAccount: primaryBankAccount.correspondentAccount,
        bik: primaryBankAccount.bik,
      };

      insertCounterpartyToDb(nextCounterparty);
      return nextCounterparty;
    });

    res.status(201).json(counterparty);
  })
);

app.put(
  '/api/counterparties/:id',
  asyncHandler(async (req, res) => {
    const counterpartyId = toTrimmedString(req.params.id);
    if (!counterpartyId) {
      throw new ApiError(400, 'Некорректный идентификатор контрагента.');
    }

    if (!req.body || typeof req.body !== 'object') {
      throw new ApiError(400, 'Тело запроса должно быть объектом.');
    }

    const updatedCounterparty = await withDataLock(async () => updateCounterpartyByIdInDb(counterpartyId, req.body));
    res.status(200).json(updatedCounterparty);
  })
);

app.delete(
  '/api/counterparties/:id',
  asyncHandler(async (req, res) => {
    const counterpartyId = toTrimmedString(req.params.id);
    if (!counterpartyId) {
      throw new ApiError(400, 'Некорректный идентификатор контрагента.');
    }

    await withDataLock(async () => deleteCounterpartyByIdInDb(counterpartyId));
    res.status(204).end();
  })
);

app.get(
  '/api/invoices',
  asyncHandler(async (_req, res) => {
    res.status(200).json(listInvoicesFromDb());
  })
);

app.post(
  '/api/invoices',
  asyncHandler(async (req, res) => {
    const { number, date, paymentDueDate, amount, currency, status, commissionPercent, vatRate, vatMode, supplierProfileId, supplierBankAccount, items, counterpartyId } = req.body || {};

    const invoice = await withDataLock(async () => {
      let linkedCounterparty = null;
      if (isNonEmptyString(counterpartyId)) {
        linkedCounterparty = getCounterpartyByIdFromDb(counterpartyId);
        if (!linkedCounterparty) {
          throw new ApiError(404, 'Контрагент не найден.');
        }
      }

      const normalizedItems = normalizeInvoiceItems(items);
      const calculatedAmount = normalizedItems.reduce(
        (sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0),
        0
      );

      const existingInvoices = listInvoicesFromDb();
      const nextInvoice = {
        id: `inv-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        number: isNonEmptyString(number) ? number.trim() : nextInvoiceNumber(existingInvoices),
        date: isNonEmptyString(date) ? date.trim() : formatDate(),
        paymentDueDate: isNonEmptyString(paymentDueDate) ? paymentDueDate.trim() : undefined,
        amount: toNonNegativeNumber(amount, calculatedAmount),
        currency: toCurrency(currency),
        status: toInvoiceStatus(status),
        commissionPercent: toMarkupPercent(commissionPercent),
        vatRate: toVatRate(vatRate),
        vatMode: toVatMode(vatMode),
        supplierProfileId: resolveSupplierProfileIdForInvoice(supplierProfileId),
        supplierBankAccount: toSupplierBankAccount(supplierBankAccount),
        items: normalizedItems,
        counterpartyId: linkedCounterparty ? linkedCounterparty.id : undefined,
      };

      insertInvoiceToDb(nextInvoice);
      return nextInvoice;
    });

    res.status(201).json(invoice);
  })
);

app.put(
  '/api/invoices/:id',
  asyncHandler(async (req, res) => {
    const invoiceId = toTrimmedString(req.params.id);
    if (!invoiceId) {
      throw new ApiError(400, 'Некорректный идентификатор счёта.');
    }

    if (!req.body || typeof req.body !== 'object') {
      throw new ApiError(400, 'Тело запроса должно быть объектом.');
    }

    const updatedInvoice = await withDataLock(async () => updateInvoiceByIdInDb(invoiceId, req.body));
    res.status(200).json(updatedInvoice);
  })
);

app.delete(
  '/api/invoices/:id',
  asyncHandler(async (req, res) => {
    const invoiceId = toTrimmedString(req.params.id);
    if (!invoiceId) {
      throw new ApiError(400, 'Некорректный идентификатор счёта.');
    }

    await withDataLock(async () => deleteInvoiceByIdInDb(invoiceId));
    res.status(204).end();
  })
);

app.get(
  '/api/templates',
  asyncHandler(async (_req, res) => {
    res.status(200).json(listTemplatesFromDb());
  })
);

app.get(
  '/api/template-variables',
  asyncHandler(async (_req, res) => {
    res.status(200).json(deepClone(DEFAULT_TEMPLATE_VARIABLES));
  })
);

app.post(
  '/api/templates',
  asyncHandler(async (req, res) => {
    const { name, type, content, css, isActive = true, variables } = req.body || {};

    if (!isNonEmptyString(name)) {
      throw new ApiError(400, 'Поле "name" обязательно.');
    }

    if (!isNonEmptyString(type)) {
      throw new ApiError(400, 'Поле "type" обязательно.');
    }

    const template = await withDataLock(async () => {
      const nextTemplate = {
        id: `tpl-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        name: name.trim(),
        type: type.trim(),
        version: '1.0',
        updatedAt: formatDate(),
        isActive: Boolean(isActive),
        content: normalizeTemplateContent(content),
        css: normalizeTemplateCss(css),
        variables: normalizeTemplateVariables(variables),
      };

      insertTemplateToDb(nextTemplate);
      const createdTemplate = getTemplateByIdFromDb(nextTemplate.id);
      if (!createdTemplate) {
        throw new ApiError(500, 'Не удалось создать шаблон.');
      }
      return createdTemplate;
    });

    res.status(201).json(template);
  })
);

app.put(
  '/api/templates/:id',
  asyncHandler(async (req, res) => {
    const templateId = toTrimmedString(req.params.id);
    if (!templateId) {
      throw new ApiError(400, 'Некорректный идентификатор шаблона.');
    }

    if (!req.body || typeof req.body !== 'object') {
      throw new ApiError(400, 'Тело запроса должно быть объектом.');
    }

    const updatedTemplate = await withDataLock(async () => updateTemplateByIdInDb(templateId, req.body));
    res.status(200).json(updatedTemplate);
  })
);

app.delete(
  '/api/templates/:id',
  asyncHandler(async (req, res) => {
    const templateId = toTrimmedString(req.params.id);
    if (!templateId) {
      throw new ApiError(400, 'Некорректный идентификатор шаблона.');
    }

    await withDataLock(async () => deleteTemplateByIdInDb(templateId));
    res.status(204).end();
  })
);

app.get(
  '/api/settings',
  asyncHandler(async (_req, res) => {
    res.status(200).json(getSettingsFromDb());
  })
);

app.put(
  '/api/settings',
  asyncHandler(async (req, res) => {
    if (!req.body || typeof req.body !== 'object') {
      throw new ApiError(400, 'Тело запроса должно быть объектом.');
    }

    const settings = await withDataLock(async () => updateSettingsInDb(req.body));

    res.status(200).json(settings);
  })
);

app.post(
  '/api/generate/package',
  asyncHandler(async (req, res) => {
    const { format, fileName, files } = req.body || {};
    const normalizedFormat = String(format || 'pdf').trim().toLowerCase();

    if (normalizedFormat !== 'pdf' && normalizedFormat !== 'docx') {
      throw new ApiError(400, 'Поддерживаются только форматы pdf и docx.');
    }

    if (!Array.isArray(files) || files.length === 0) {
      throw new ApiError(400, 'Передайте массив файлов для упаковки.');
    }

    const normalizedFiles = files.map((file, index) => {
      const html = isNonEmptyString(file?.html) ? file.html : '';
      const css = isNonEmptyString(file?.css) ? file.css : '';
      const rawName = sanitizeFileName(file?.fileName, `document-${index + 1}`);

      if (!isNonEmptyString(html)) {
        throw new ApiError(400, `Для файла #${index + 1} не передан HTML.`);
      }

      return {
        html,
        css,
        fileName: rawName,
      };
    });

    const zip = new JSZip();

    if (normalizedFormat === 'pdf') {
      let browser;
      try {
        browser = await puppeteer.launch(buildPuppeteerLaunchOptions());

        for (const item of normalizedFiles) {
          const pdfBuffer = await renderPdfBufferWithPuppeteer(browser, item.html, item.css);
          zip.file(`${item.fileName}.pdf`, pdfBuffer);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error('Package PDF generation failed:', message);
        throw new ApiError(
          500,
          'PDF генерация недоступна в текущем окружении. Установите Chromium или задайте PUPPETEER_EXECUTABLE_PATH.'
        );
      } finally {
        if (browser) {
          await browser.close();
        }
      }
    } else {
      for (const item of normalizedFiles) {
        const sanitizedHtml = sanitizeDocxStyles(item.html);
        const sanitizedCss = sanitizeDocxStyles(item.css);
        const content = fullHtmlDocument(sanitizedHtml, sanitizedCss);
        const fileBuffer = await HTMLtoDOCX(content, null, {
          table: { row: { cantSplit: true } },
          footer: true,
          pageNumber: true,
          font: 'Times New Roman',
          title: 'Contract',
        });
        zip.file(`${item.fileName}.docx`, fileBuffer);
      }
    }

    const archiveBuffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
    const safeBaseName = sanitizeFileName(fileName, 'documents-package');
    res.set({
      'Content-Type': 'application/zip',
      'Content-Length': archiveBuffer.length,
      'Content-Disposition': buildContentDisposition(safeBaseName, 'zip', 'documents-package'),
    });
    res.send(archiveBuffer);
  })
);

app.post(
  '/api/generate/:format',
  asyncHandler(async (req, res) => {
    const { format } = req.params;
    const { html, css, fileName } = req.body || {};

    if (!isNonEmptyString(html)) {
      throw new ApiError(400, 'HTML content is required');
    }

    const safeBaseName = sanitizeFileName(fileName, 'contract');
    if (format === 'pdf') {
      let browser;
      try {
        browser = await puppeteer.launch(buildPuppeteerLaunchOptions());
        const pdfBuffer = await renderPdfBufferWithPuppeteer(browser, html, css);

        res.set({
          'Content-Type': 'application/pdf',
          'Content-Length': pdfBuffer.length,
          'Content-Disposition': buildContentDisposition(safeBaseName, 'pdf'),
        });
        res.send(pdfBuffer);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error('PDF generation failed:', message);
        throw new ApiError(
          500,
          'PDF генерация недоступна в текущем окружении. Установите Chromium или задайте PUPPETEER_EXECUTABLE_PATH.'
        );
      } finally {
        if (browser) {
          await browser.close();
        }
      }

      return;
    }

    if (format === 'docx') {
      const sanitizedHtml = sanitizeDocxStyles(html);
      const sanitizedCss = sanitizeDocxStyles(css);
      const content = fullHtmlDocument(sanitizedHtml, sanitizedCss);
      const fileBuffer = await HTMLtoDOCX(content, null, {
        table: { row: { cantSplit: true } },
        footer: true,
        pageNumber: true,
        font: 'Times New Roman',
        title: 'Contract',
      });

      res.set({
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Length': fileBuffer.length,
        'Content-Disposition': buildContentDisposition(safeBaseName, 'docx'),
      });
      res.send(fileBuffer);
      return;
    }

    throw new ApiError(404, 'Unsupported format');
  })
);

app.use((error, _req, res, _next) => {
  const statusCode = Number(error.statusCode) || 500;
  const message = isNonEmptyString(error.message) ? error.message : 'Internal server error';

  if (statusCode >= 500) {
    console.error(error);
  }

  res.status(statusCode).json({
    error: message,
  });
});

const startServer = async () => {
  try {
    await initDatabase();
    app.listen(PORT, () => {
      console.log(`DocuFlow Backend running on http://localhost:${PORT}`);
      console.log(`SQLite storage active: ${DB_FILE}`);
    });
  } catch (error) {
    console.error('Failed to start backend:', error);
    process.exit(1);
  }
};

module.exports = {
  app,
  PORT,
  DATA_FILE,
  DB_FILE,
  startServer,
  initDatabase,
  ApiError,
  asyncHandler,
  isNonEmptyString,
  formatDate,
  buildDashboardStats,
  normalizeTemplateCss,
  sanitizeDocxStyles,
  fullHtmlDocument,
  buildContentDisposition,
  buildPuppeteerLaunchOptions,
  renderPdfBufferWithPuppeteer,
  getTemplateForContract,
  getTemplateByIdFromDb,
  getCounterpartyByIdFromDb,
  getInvoiceByIdFromDb,
  listContractsFromDb,
  listInvoicesFromDb,
  listCounterpartiesFromDb,
  listTemplatesFromDb,
  getSettingsFromDb,
  buildContractSnapshotPayload,
  toVatRate,
  toVatMode,
  toMarkupPercent,
  toMarkupMode,
  toMarkupCalcMode,
  toNonNegativeNumber,
  toPositiveInteger,
};

if (require.main === module) {
  startServer();
}
