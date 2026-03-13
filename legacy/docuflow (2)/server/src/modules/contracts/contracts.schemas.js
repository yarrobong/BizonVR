const { z } = require('zod');

const contractIdSchema = z.string().min(1);

module.exports = {
  contractIdSchema,
};
