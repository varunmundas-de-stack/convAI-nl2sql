const jwt = require('jsonwebtoken');

function firstCube(query) {
  const members = [
    ...(query.measures || []),
    ...(query.dimensions || []),
    ...((query.timeDimensions || []).map((td) => td.dimension).filter(Boolean)),
  ];
  const first = members.find((m) => typeof m === 'string' && m.includes('.'));
  return first ? first.split('.')[0] : 'fact_secondary_sales';
}

module.exports = {
  checkAuth: async (req, auth) => {
    if (!auth) {
      throw new Error('No authorization token provided');
    }
    const secret = process.env.CUBEJS_API_SECRET;
    if (!secret) {
      throw new Error('CUBEJS_API_SECRET is not configured');
    }
    req.securityContext = jwt.verify(auth.replace(/^Bearer\s+/i, ''), secret, {
      algorithms: ['HS256'],
    });
  },

  contextToAppId: ({ securityContext }) => {
    const clientId = securityContext?.clientId || 'default';
    return `APP_${clientId}`;
  },

  contextToOrchestratorId: ({ securityContext }) => {
    const clientId = securityContext?.clientId || 'default';
    return `ORCH_${clientId}`;
  },

  queryRewrite: (query, { securityContext }) => {
    if (!securityContext) return query;

    const role = String(securityContext.role || '').toUpperCase();
    const cube = firstCube(query);
    const roleToField = {
      SO: 'so_name',
      ASM: 'asm_name',
      ZSM: 'zsm_name',
    };
    const roleToCode = {
      SO: securityContext.so_code || securityContext.hierarchy_code,
      ASM: securityContext.asm_code || securityContext.hierarchy_code,
      ZSM: securityContext.zsm_code || securityContext.hierarchy_code,
    };

    if (roleToField[role] && roleToCode[role]) {
      query.filters = query.filters || [];
      query.filters.push({
        member: `${cube}.${roleToField[role]}`,
        operator: 'equals',
        values: [roleToCode[role]],
      });
    }

    return query;
  },
};
