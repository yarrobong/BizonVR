const { HttpError } = require('../errors/http-error');

const errorHandler = (error, _req, res, _next) => {
  const normalized =
    error instanceof HttpError
      ? error
      : new HttpError(Number(error?.statusCode) || 500, 'INTERNAL_ERROR', error?.message || 'Internal server error');

  if (normalized.statusCode >= 500) {
    console.error(error);
  }

  res.status(normalized.statusCode).json({
    error: {
      code: normalized.code,
      message: normalized.message,
      details: normalized.details,
    },
  });
};

module.exports = { errorHandler };
