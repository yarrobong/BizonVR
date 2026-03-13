const puppeteer = require('puppeteer');
const HTMLtoDOCX = require('html-to-docx');
const JSZip = require('jszip');
const legacy = require('../../legacy/legacy-app');
const { HttpError } = require('../../app/errors/http-error');

const exportSingle = async ({ format, html, css = '', fileName = 'contract' }) => {
  if (!legacy.isNonEmptyString(html)) {
    throw new HttpError(400, 'HTML_REQUIRED', 'HTML content is required');
  }

  const normalizedFormat = String(format || '').trim().toLowerCase();
  if (normalizedFormat !== 'pdf' && normalizedFormat !== 'docx') {
    throw new HttpError(400, 'FORMAT_INVALID', 'Only pdf and docx are supported');
  }

  const safeBaseName = String(fileName || 'contract').trim() || 'contract';

  if (normalizedFormat === 'pdf') {
    let browser;
    try {
      browser = await puppeteer.launch(legacy.buildPuppeteerLaunchOptions());
      const pdfBuffer = await legacy.renderPdfBufferWithPuppeteer(browser, html, css);

      return {
        buffer: pdfBuffer,
        contentType: 'application/pdf',
        extension: 'pdf',
        contentDisposition: legacy.buildContentDisposition(safeBaseName, 'pdf'),
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new HttpError(
        500,
        'PDF_GENERATION_FAILED',
        'PDF generation is unavailable in the current environment',
        { reason: message }
      );
    } finally {
      if (browser) {
        await browser.close();
      }
    }
  }

  const sanitizedHtml = legacy.sanitizeDocxStyles(html);
  const sanitizedCss = legacy.sanitizeDocxStyles(css);
  const content = legacy.fullHtmlDocument(sanitizedHtml, sanitizedCss);
  const fileBuffer = await HTMLtoDOCX(content, null, {
    table: { row: { cantSplit: true } },
    footer: true,
    pageNumber: true,
    font: 'Times New Roman',
    title: 'Contract',
  });

  return {
    buffer: fileBuffer,
    contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    extension: 'docx',
    contentDisposition: legacy.buildContentDisposition(safeBaseName, 'docx'),
  };
};

const exportPackage = async ({ format, fileName, files }) => {
  const normalizedFormat = String(format || '').trim().toLowerCase();
  if (normalizedFormat !== 'pdf' && normalizedFormat !== 'docx') {
    throw new HttpError(400, 'FORMAT_INVALID', 'Only pdf and docx are supported');
  }

  if (!Array.isArray(files) || files.length === 0) {
    throw new HttpError(400, 'FILES_REQUIRED', 'files[] is required');
  }

  const zip = new JSZip();
  for (let index = 0; index < files.length; index += 1) {
    const item = files[index] || {};
    const fileNameSafe = String(item.fileName || `document-${index + 1}`).trim() || `document-${index + 1}`;
    const generated = await exportSingle({
      format: normalizedFormat,
      html: item.html,
      css: item.css,
      fileName: fileNameSafe,
    });
    zip.file(`${fileNameSafe}.${generated.extension}`, generated.buffer);
  }

  const archiveBuffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  const safeBaseName = String(fileName || 'documents-package').trim() || 'documents-package';

  return {
    buffer: archiveBuffer,
    contentType: 'application/zip',
    contentDisposition: legacy.buildContentDisposition(safeBaseName, 'zip', 'documents-package'),
  };
};

module.exports = {
  exportSingle,
  exportPackage,
};
