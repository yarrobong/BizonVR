const { HttpError } = require('../../app/errors/http-error');

const validate = (schema, payload, code = 'VALIDATION_ERROR') => {
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new HttpError(400, code, 'Validation failed', parsed.error.flatten());
  }
  return parsed.data;
};

module.exports = { validate };
