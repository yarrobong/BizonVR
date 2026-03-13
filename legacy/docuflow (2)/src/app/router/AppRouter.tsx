import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { LegacyPage } from '../../pages/legacy/LegacyPage';

export const AppRouter: React.FC = () => {
  return (
    <Routes>
      <Route path="/*" element={<LegacyPage />} />
    </Routes>
  );
};
