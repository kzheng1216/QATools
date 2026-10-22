import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from '../Login';
import Home from '../Home';
import Userlist from '../user_list';
import RunTestcasesReportHtml from '../testcases/run_testcases_report_html';
import RunTestcasesReportJson from '../testcases/run_testcases_report_json';
import Case01 from "../cases/case01";
import Case02 from "../cases/case02";
import Case03 from "../cases/case03";
import Case04 from "../cases/case04";
import CaseHook from "../cases/caseHook";
import Case05 from "../cases/case05";
import Case06 from "../cases/UseState01";
import Case07 from "../cases/case07";
import Case08 from "../cases/UseEffect01";
import Case09 from "../cases/case09";
import Counter from "../cases/redux/Counter";
import Case_table01 from "../cases/table/case_table01";
import Wcase01 from "../cases/websocket/wcase01";

const routes = [
    { path: "/", element: <Login /> },
    { path: "/login", element: <Login /> },
    { path: "/home", element: <Home /> },
    { path: "/user_list", element: <Userlist /> },
    { path: "/run_testcases_report_html", element: <RunTestcasesReportHtml /> },
    { path: "/run_testcases_report_json", element: <RunTestcasesReportJson /> },
    { path: "/cases/case01", element: <Case01 /> },
    { path: "/cases/case02", element: <Case02 /> },
    { path: "/cases/case03", element: <Case03 /> },
    { path: "/cases/case04", element: <Case04 /> },
    { path: "/cases/caseHook", element: <CaseHook /> },
    { path: "/cases/case05", element: <Case05 /> },
    { path: "/cases/UseState01", element: <Case06 /> },
    { path: "/cases/case07", element: <Case07 /> },
    { path: "/cases/UseEffect01", element: <Case08 /> },
    { path: "/cases/case09", element: <Case09 /> },
    { path: "/cases/redux/Counter", element: <Counter /> },
    { path: "/cases/table/case_table01", element: <Case_table01 /> },
    { path: "/cases/websocket/wcase01", element: <Wcase01 /> },
    { path: "*", element: <Navigate to="/login" /> },
];

const MyRouter = () => {
    return (
        <BrowserRouter>
            <Routes>
                {routes.map(({ path, element }) => (
                    <Route key={path} path={path} element={element} />
                ))}
            </Routes>
        </BrowserRouter>
    );
};

export default MyRouter;