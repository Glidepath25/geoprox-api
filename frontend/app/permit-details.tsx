import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Linking,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

const EXPO_PUBLIC_BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

interface Permit {
  id: string;
  permit_number: string;
  works_type: string;
  location: string;
  address: string;
  latitude: number;
  longitude: number;
  highway_authority: string;
  status: string;
  proximity_risk_assessment: string;
  created_at: string;
  inspection_status?: string;
  inspection_results?: {
    bituminous: string;
    sub_base: string;
  } | null;
  sample_status?: string;
}

export default function PermitDetailsScreen() {
  const router = useRouter();
  const { permitId } = useLocalSearchParams();
  
  const [permit, setPermit] = useState<Permit | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadPermitDetails();
  }, []);

  const loadPermitDetails = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      
      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/permits/${permitId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setPermit(data);
      } else if (response.status === 401) {
        await AsyncStorage.clear();
        router.replace('/');
      } else {
        Alert.alert('Error', 'Failed to load permit details');
      }
    } catch (error) {
      console.error('Load permit error:', error);
      Alert.alert('Error', 'Network error loading permit');
    } finally {
      setLoading(false);
    }
  };

  const openGoogleMaps = (latitude: number, longitude: number) => {
    const url = `https://www.google.com/maps?q=${latitude},${longitude}`;
    Linking.openURL(url).catch(() => {
      Alert.alert('Error', 'Unable to open Google Maps');
    });
  };

  const getRiskAssessmentColor = (risk: string) => {
    switch (risk.toLowerCase()) {
      case 'low':
        return '#10b981';
      case 'medium':
        return '#f59e0b';
      case 'high':
        return '#ef4444';
      default:
        return '#6b7280';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'pending':
        return '#f59e0b';
      case 'wip':
        return '#8b5cf6';
      case 'completed':
        return '#10b981';
      default:
        return '#6b7280';
    }
  };

  const handleSiteInspection = () => {
    router.push({
      pathname: '/inspection',
      params: { permitId: permitId }
    });
  };

  const handleSampleTesting = () => {
    router.push({
      pathname: '/sample-testing',
      params: { permitId: permitId }
    });
  };

  const openDesktopArtefacts = () => {
    // Mock S3 URL for artifacts - in production this would be the real S3 link
    Alert.alert(
      'Desktop Assessment Artefacts',
      'This would open the S3 storage containing desktop assessment files and documents.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Open S3 Storage', onPress: () => {
          // In production: Linking.openURL(s3_url)
          Alert.alert('Info', 'Desktop artefacts would open in browser');
        }}
      ]
    );
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading permit details...</Text>
      </View>
    );
  }

  if (!permit) {
    return (
      <View style={styles.errorContainer}>
        <Text style={styles.errorText}>Permit not found</Text>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backButtonText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.headerBackButton}>
          <Ionicons name="arrow-back" size={24} color="#2563eb" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Permit Details</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Permit Overview */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{permit.permit_number}</Text>
          
          <View style={styles.permitDetails}>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Works Type:</Text>
              <Text style={styles.detailValue}>{permit.works_type}</Text>
            </View>
            
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Location:</Text>
              <Text style={styles.detailValue}>{permit.location}</Text>
            </View>
            
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Highway Authority:</Text>
              <Text style={styles.detailValue}>{permit.highway_authority}</Text>
            </View>
            
            <TouchableOpacity 
              style={styles.coordinatesRow}
              onPress={() => openGoogleMaps(permit.latitude, permit.longitude)}
              activeOpacity={0.7}
            >
              <Text style={styles.detailLabel}>Coordinates:</Text>
              <Text style={styles.coordinatesText}>
                {permit.latitude.toFixed(6)}, {permit.longitude.toFixed(6)}
              </Text>
              <Ionicons name="open-outline" size={16} color="#2563eb" />
            </TouchableOpacity>
          </View>
        </View>

        {/* Desktop Assessment */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <View>
              <Text style={styles.sectionTitle}>Desktop</Text>
              <Text style={styles.sectionSubtitle}>Proximity Risk Assessment</Text>
            </View>
            <View style={[styles.statusBadge, { backgroundColor: getStatusColor('completed') }]}>
              <Text style={styles.statusText}>Complete</Text>
            </View>
          </View>

          <View style={styles.assessmentContent}>
            <View style={styles.resultRow}>
              <Text style={styles.resultLabel}>Result:</Text>
              <View style={[styles.riskBadge, { backgroundColor: getRiskAssessmentColor(permit.proximity_risk_assessment) }]}>
                <Text style={styles.riskText}>{permit.proximity_risk_assessment}</Text>
              </View>
            </View>

            <TouchableOpacity 
              style={styles.artefactsButton}
              onPress={openDesktopArtefacts}
            >
              <Ionicons name="folder-open" size={20} color="#2563eb" />
              <Text style={styles.artefactsText}>View Artefacts</Text>
              <Ionicons name="chevron-forward" size={16} color="#2563eb" />
            </TouchableOpacity>
          </View>
        </View>

        {/* Site Inspection */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <View>
              <Text style={styles.sectionTitle}>Site</Text>
              <Text style={styles.sectionSubtitle}>Site Inspection</Text>
            </View>
            <View style={[styles.statusBadge, { backgroundColor: getStatusColor(permit.inspection_status || 'pending') }]}>
              <Text style={styles.statusText}>
                {permit.inspection_status === 'wip' ? 'WIP' : 
                 permit.inspection_status === 'completed' ? 'Complete' : 'Pending'}
              </Text>
            </View>
          </View>

          {permit.inspection_results && (
            <View style={styles.resultsContainer}>
              <View style={styles.resultRow}>
                <Text style={styles.resultLabel}>Bituminous:</Text>
                <View style={[styles.resultBadge, { backgroundColor: permit.inspection_results.bituminous === 'Green' ? '#10b981' : '#ef4444' }]}>
                  <Text style={styles.resultText}>{permit.inspection_results.bituminous}</Text>
                </View>
              </View>
              
              <View style={styles.resultRow}>
                <Text style={styles.resultLabel}>Sub-Base:</Text>
                <View style={[styles.resultBadge, { backgroundColor: permit.inspection_results.sub_base === 'Green' ? '#10b981' : '#ef4444' }]}>
                  <Text style={styles.resultText}>{permit.inspection_results.sub_base}</Text>
                </View>
              </View>
            </View>
          )}

          <TouchableOpacity 
            style={styles.actionButton}
            onPress={handleSiteInspection}
          >
            <Ionicons name="clipboard" size={20} color="#ffffff" />
            <Text style={styles.actionButtonText}>
              {permit.inspection_status === 'completed' ? 'View Site Inspection' : 'Complete Site Inspection'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Sample Testing */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <View>
              <Text style={styles.sectionTitle}>Sample</Text>
              <Text style={styles.sectionSubtitle}>Sample Testing</Text>
            </View>
            <View style={[styles.statusBadge, { backgroundColor: getStatusColor(permit.sample_status || 'not_required') }]}>
              <Text style={styles.statusText}>
                {permit.sample_status === 'wip' ? 'WIP' : 
                 permit.sample_status === 'completed' ? 'Complete' : 
                 permit.sample_status === 'pending' ? 'Pending' : 'Not Required'}
              </Text>
            </View>
          </View>

          <TouchableOpacity 
            style={styles.actionButton}
            onPress={handleSampleTesting}
          >
            <Ionicons name="flask" size={20} color="#ffffff" />
            <Text style={styles.actionButtonText}>
              {permit.sample_status === 'completed' ? 'View Sample Testing' : 'Complete Sample Testing'}
            </Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f8fafc',
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: '#6b7280',
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f8fafc',
  },
  errorText: {
    fontSize: 18,
    color: '#ef4444',
    marginBottom: 16,
  },
  backButton: {
    backgroundColor: '#2563eb',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
  backButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#ffffff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  headerBackButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
  },
  placeholder: {
    width: 40,
  },
  scrollView: {
    flex: 1,
  },
  section: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  sectionSubtitle: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  permitDetails: {
    marginTop: 16,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  detailLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
    minWidth: 100,
  },
  detailValue: {
    fontSize: 14,
    color: '#6b7280',
    flex: 1,
  },
  coordinatesRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  coordinatesText: {
    fontSize: 14,
    color: '#2563eb',
    textDecorationLine: 'underline',
    flex: 1,
    marginLeft: 4,
    marginRight: 8,
  },
  assessmentContent: {
    marginTop: 8,
  },
  resultRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  resultLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
    marginRight: 12,
  },
  riskBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  riskText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  resultBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  resultText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  artefactsButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#eff6ff',
    padding: 12,
    borderRadius: 8,
    marginTop: 8,
  },
  artefactsText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#2563eb',
    marginLeft: 8,
    flex: 1,
  },
  resultsContainer: {
    backgroundColor: '#f9fafb',
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#2563eb',
    padding: 16,
    borderRadius: 8,
    marginTop: 8,
  },
  actionButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
});