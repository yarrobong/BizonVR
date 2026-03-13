const test = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');
const { createApp } = require('../src/app/create-app');
const { initDatabase } = require('../src/legacy/legacy-app');

let app;

test.before(async () => {
  await initDatabase();
  app = createApp();
});

test('GET /api/v2/contracts returns array', async () => {
  const response = await request(app).get('/api/v2/contracts');
  assert.equal(response.statusCode, 200);
  assert.equal(Array.isArray(response.body), true);
});

test('GET /api/v2/settings returns object', async () => {
  const response = await request(app).get('/api/v2/settings');
  assert.equal(response.statusCode, 200);
  assert.equal(typeof response.body, 'object');
});

test('GET /api/v1/bootstrap returns compatibility payload', async () => {
  const response = await request(app).get('/api/v1/bootstrap');
  assert.equal(response.statusCode, 200);
  assert.equal(Array.isArray(response.body.contracts), true);
  assert.equal(Array.isArray(response.body.counterparties), true);
});

test('GET /api/v2/templates contains supply legal entities template', async () => {
  const response = await request(app).get('/api/v2/templates');
  assert.equal(response.statusCode, 200);
  assert.equal(Array.isArray(response.body), true);
  assert.equal(response.body.some((template) => template.id === 'tpl-supply-legal-entities-2026'), true);
});

test('POST /api/contracts/preview renders legal entities template without placeholders', async () => {
  const templatesResponse = await request(app).get('/api/v2/templates');
  const legalTemplate = templatesResponse.body.find((template) => template.id === 'tpl-supply-legal-entities-2026');
  assert.equal(Boolean(legalTemplate), true);

  const response = await request(app)
    .post('/api/contracts/preview')
    .send({
      type: 'Договор поставки',
      templateId: 'tpl-supply-legal-entities-2026',
      number: 'Д-2026-054',
      amount: 1060,
      paymentTerms: 3,
      includeDelivery: true,
      deliveryDate: '16.02.2026',
      contractData: {
        contractScenario: 'supply_legal_entities',
        supplierSignerPosition: 'индивидуальный предприниматель',
        supplierSignerName: 'Едигарьев Ярослав Алексеевич',
        supplierSignerBasis: 'свидетельства о государственной регистрации в качестве ИП',
        buyerSignerPosition: 'директор',
        buyerSignerName: 'Щеголев Александр Викторович',
        buyerSignerBasis: 'Устава',
      },
      counterparty: {
        id: 'preview-buyer',
        legalType: 'ooo',
        name: 'ООО "СПЕКТР"',
        inn: '7448225232',
        kpp: '744801001',
        ogrn: '1207400021036',
        address: 'г. Челябинск, пр-кт Свердловский, д. 2, оф. 207',
        directorName: 'Щеголев Александр Викторович',
        contactPerson: 'Щеголев Александр Викторович',
        email: 'buyer@example.com',
        bankName: 'ПАО СБЕРБАНК',
        checkingAccount: '40702810772000039956',
        correspondentAccount: '30101810700000000602',
        bik: '047501602',
      },
      invoice: {
        id: 'preview-invoice',
        number: 'СЧ-2026-054',
        date: '16.02.2026',
        amount: 1060,
        currency: 'RUB',
        status: 'Не оплачен',
        commissionPercent: 6,
        vatRate: 'none',
        vatMode: 'included',
        supplierProfileId: 'company-1',
        items: [
          {
            id: 'line-1',
            description: 'Кабель Type-C',
            quantity: 1,
            unit: 'шт',
            price: 1000,
          },
        ],
      },
    });

  assert.equal(response.statusCode, 200);
  assert.equal(typeof response.body.html, 'string');
  assert.equal(response.body.templateId, 'tpl-supply-legal-entities-2026');
  assert.equal(response.body.html.includes('{{'), false);
  assert.equal(response.body.html.includes('ООО &quot;СПЕКТР&quot;'), true);
  assert.equal(response.body.html.includes('Щеголев Александр Викторович'), true);
  assert.match(response.body.html, /предпринимательской деятельности/u);
  assert.equal(response.body.html.includes('личных нужд'), false);
  assert.equal(response.body.html.includes('за счет Продавца'), false);
  assert.equal(response.body.html.includes('выбрать/заполнить'), false);
  assert.match(response.body.html, /оплата производится в течение 5 \(пяти\) рабочих дней с даты подписания Договора/u);
  assert.match(response.body.html, /считается полученным по правилам п\. 10\.1/u);
  assert.match(response.body.html, /возврат остатка предоплаты производится в течение 7 \(семи\) рабочих дней/u);
  assert.match(response.body.html, /Услуги ТК оплачивает Покупатель/u);
  assert.match(response.body.html, /в течение 5 \(пяти\) рабочих дней с даты поступления оплаты/u);
  assert.match(response.body.html, /риск случайной гибели\/повреждения Товара переходит к Покупателю в момент вручения/u);
  assert.match(response.body.html, /Если доставка осуществляется до терминала ТК\/ПВЗ/u);
  assert.match(response.body.html, /Претензии по некомплектности внутри упаковки рассматриваются в срок, установленный п\. 5\.2/u);
  assert.match(response.body.html, /документально подтвержденных расходов Поставщика/u);
  assert.match(response.body.html, /отчет сервера отправителя, квитанция о доставке или иной технический лог/u);
  assert.match(response.body.html, /согласование существенных условий поставки/u);
  assert.match(response.body.html, /первичного брака \(DOA\)/u);
  assert.match(response.body.html, /фото\/видеофиксацию комплектации, упаковки и передачи/u);
  assert.match(response.body.html, /НДС не применяется в связи с применением Поставщиком/u);
  assert.match(response.body.html, /1[\s\u00A0\u202F]060,00/u);
});

test('POST /api/contracts/preview omits buyer KPP line for IP buyer', async () => {
  const response = await request(app)
    .post('/api/contracts/preview')
    .send({
      type: 'Договор поставки',
      templateId: 'tpl-supply-legal-entities-2026',
      number: 'Д-2026-056',
      amount: 5000,
      paymentTerms: 3,
      counterparty: {
        id: 'preview-buyer-ip',
        legalType: 'ip',
        name: 'ИП Петров Петр Петрович',
        inn: '667907832209',
        ogrnip: '325665800130159',
        address: 'г. Екатеринбург',
        email: 'ip@example.com',
      },
      invoice: {
        id: 'preview-invoice-ip',
        number: 'СЧ-2026-056',
        date: '16.02.2026',
        amount: 5000,
        currency: 'RUB',
        status: 'Не оплачен',
        commissionPercent: 6,
        vatRate: 'none',
        vatMode: 'included',
        supplierProfileId: 'company-1',
        items: [{ id: 'line-1', description: 'Товар', quantity: 1, unit: 'шт', price: 5000 }],
      },
    });

  assert.equal(response.statusCode, 200);
  assert.equal(response.body.html.includes('ИНН 667907832209 / КПП'), false);
});

test('POST /api/contracts/preview rejects legal entities template for person buyer', async () => {
  const response = await request(app)
    .post('/api/contracts/preview')
    .send({
      type: 'Договор поставки',
      templateId: 'tpl-supply-legal-entities-2026',
      number: 'Д-2026-055',
      counterparty: {
        id: 'preview-person',
        legalType: 'person',
        name: 'Иванов Иван Иванович',
        inn: '',
        address: 'г. Екатеринбург',
      },
      invoice: {
        id: 'preview-invoice-person',
        number: 'СЧ-2026-055',
        date: '16.02.2026',
        amount: 1000,
        currency: 'RUB',
        status: 'Не оплачен',
        vatRate: 'none',
        vatMode: 'included',
        supplierProfileId: 'company-1',
        items: [{ id: 'line-1', description: 'Товар', quantity: 1, unit: 'шт', price: 1000 }],
      },
    });

  assert.equal(response.statusCode, 400);
  assert.match(String(response.body?.error || ''), /ООО|АО|ИП|Физлица/u);
});
