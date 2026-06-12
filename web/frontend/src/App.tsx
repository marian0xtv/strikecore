import { Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Home from "./pages/Home";
import Agents from "./pages/Agents";
import Dossiers from "./pages/Dossiers";
import DossierDetail from "./pages/DossierDetail";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";
import Improvements from "./pages/Improvements";
import Cost from "./pages/Cost";
import Hephaestus from "./pages/Hephaestus";
import Console from "./pages/Console";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-y-auto scrollbar-thin px-6 py-5">
          <Routes>
            <Route path="/"                    element={<Home />} />
            <Route path="/agents"              element={<Agents />} />
            <Route path="/dossiers"            element={<Dossiers />} />
            <Route path="/dossiers/:id"        element={<DossierDetail />} />
            <Route path="/runs"                element={<Runs />} />
            <Route path="/runs/:id"            element={<RunDetail />} />
            <Route path="/improvements"        element={<Improvements />} />
            <Route path="/cost"                element={<Cost />} />
            <Route path="/hephaestus"          element={<Hephaestus />} />
            <Route path="/console"             element={<Console />} />
            <Route path="/settings"            element={<Settings />} />
            <Route path="*" element={<div className="text-muted">404 — not found</div>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
