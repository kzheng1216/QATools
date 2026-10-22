import React, { useEffect, useState } from 'react';
import { Spin, Alert, Typography } from 'antd';
import axios from 'axios';

const { Text } = Typography;

const RunTestcasesReportJson: React.FC = () => {
    let token = localStorage.getItem('token');
    const config = {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    };

    const [reportData, setReportData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await axios.post('http://localhost:9882/api/run_tests', {
                    "mark_type": "ui",
                    "report_type": "json"
                }, config);
                setReportData(response.data);
            } catch (error) {
                console.error('Error fetching data:', error);
                setError('Failed to fetch report data.');
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, []);

    if (loading) {
        return (
            <div style={{ textAlign: 'center', marginTop: '20px' }}>
                <Spin tip="Loading report..." />
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ textAlign: 'center', marginTop: '20px' }}>
                <Alert message="Error" description={error} type="error" showIcon />
            </div>
        );
    }

    return (
        <div style={{ padding: '20px' }}>
            <Text strong>Report Data:</Text>
            <pre>{JSON.stringify(reportData, null, 2)}</pre>
        </div>
    );
};

export default RunTestcasesReportJson;