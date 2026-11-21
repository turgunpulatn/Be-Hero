import { Navigate, Route, Routes } from "react-router-dom";

import WorkspaceLayout from "./layouts/WorkspaceLayout";
import Account from "./pages/Account";
import Chat from "./pages/Chat";
import DocumentPage from "./pages/DocumentPage";
import Goal from "./pages/Goal";
import Login from "./pages/Login";
import Payments from "./pages/Payments";
import Portfolio from "./pages/Portfolio";
import Results from "./pages/Results";
import Upload from "./pages/Upload";
import Verify from "./pages/Verify";

export default function App() {
  return (
    <Routes>
      <Route path="/kirish" element={<Login />} />
      <Route path="/kirish/tasdiqlash" element={<Verify />} />
      <Route element={<WorkspaceLayout />}>
        <Route path="/hujjatlar" element={<Portfolio />} />
        <Route path="/yuklash" element={<Upload />} />
        <Route path="/hujjat/:docId/maqsad" element={<Goal />} />
        <Route path="/tahlil/:reviewId" element={<Results />} />
        <Route path="/tahlil/:reviewId/hujjat" element={<DocumentPage />} />
        <Route path="/tahlil/:reviewId/chat" element={<Chat />} />
        <Route path="/hisob" element={<Account />} />
        <Route path="/tolov" element={<Payments />} />
      </Route>
      <Route path="*" element={<Navigate to="/hujjatlar" replace />} />
    </Routes>
  );
}
