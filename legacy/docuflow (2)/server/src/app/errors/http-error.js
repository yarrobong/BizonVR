class HttpError extends Error {
  constructor(statusCode, code, message, details) {
    super(message || 'Unexpected error');
    this.name = 'HttpError';
    this.statusCode = Number(statusCode) || 500;
    this.code = code || 'INTERNAL_ERROR';
    this.details = details;
  }
}

module.exports = { HttpError };
