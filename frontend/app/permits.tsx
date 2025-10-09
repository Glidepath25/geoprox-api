import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  TouchableOpacity,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  Alert,
  Linking,
  TextInput,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
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

export default function PermitsScreen() {
  const [permits, setPermits] = useState<Permit[]>([]);
  const [filteredPermits, setFilteredPermits] = useState<Permit[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [user, setUser] = useState(null);
  const router = useRouter();

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const userData = await AsyncStorage.getItem('user');
      
      if (!token) {
        router.replace('/');
        return;
      }
      
      if (userData) {
        setUser(JSON.parse(userData));
      }
      
      await loadPermits();
    } catch (error) {
      console.error('Auth check error:', error);
      router.replace('/');
    }
  };

  const loadPermits = async (search: string = '') => {
    try {
      const token = await AsyncStorage.getItem('token');
      
      const url = new URL(`${EXPO_PUBLIC_BACKEND_URL}/api/permits`);
      if (search.trim()) {
        url.searchParams.append('search', search.trim());
      }
      
      const response = await fetch(url.toString(), {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setPermits(data);
        setFilteredPermits(data);
      } else if (response.status === 401) {
        await AsyncStorage.clear();
        router.replace('/');
      } else {
        Alert.alert('Error', 'Failed to load permits');
      }
    } catch (error) {
      console.error('Load permits error:', error);
      Alert.alert('Error', 'Network error loading permits');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleSearch = (text: string) => {
    setSearchQuery(text);
    if (text.trim() === '') {
      setFilteredPermits(permits);
    } else {
      const filtered = permits.filter(permit =>
        permit.permit_number.toLowerCase().includes(text.toLowerCase())
      );
      setFilteredPermits(filtered);
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    loadPermits();
  };

  const handleLogout = async () => {
    Alert.alert(
      'Logout',
      'Are you sure you want to logout?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Logout',
          style: 'destructive',
          onPress: async () => {
            await AsyncStorage.clear();
            router.replace('/');
          },
        },
      ]
    );
  };

  const handlePermitPress = (permit: Permit) => {
    router.push({
      pathname: '/inspection',
      params: { permitId: permit.id }
    });
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

  const renderPermitCard = ({ item }: { item: Permit }) => (
    <TouchableOpacity
      style={styles.permitCard}
      onPress={() => handlePermitPress(item)}
      activeOpacity={0.7}
    >
      <View style={styles.cardHeader}>
        <View style={styles.headerLeft}>
          <Text style={styles.permitNumber}>{item.permit_number}</Text>
          <Text style={styles.permitName}>{item.permit_name}</Text>
        </View>
        <View style={styles.headerRight}>
          <View style={[styles.statusBadge, { backgroundColor: getStatusColor(item.status) }]}>
            <Text style={styles.statusText}>{item.status}</Text>
          </View>
          {item.inspection_status === 'completed' && item.inspection_results && (
            <View style={styles.inspectionResults}>
              <View style={[styles.resultBadge, { backgroundColor: item.inspection_results.bituminous === 'Green' ? '#10b981' : '#ef4444' }]}>
                <Text style={styles.resultText}>B: {item.inspection_results.bituminous}</Text>
              </View>
              <View style={[styles.resultBadge, { backgroundColor: item.inspection_results.sub_base === 'Green' ? '#10b981' : '#ef4444' }]}>
                <Text style={styles.resultText}>S: {item.inspection_results.sub_base}</Text>
              </View>
            </View>
          )}
        </View>
      </View>
      
      <View style={styles.cardContent}>
        <View style={styles.detailRow}>
          <Ionicons name="construct" size={16} color="#6b7280" />
          <Text style={styles.detailText}>{item.works_type}</Text>
        </View>
        
        <View style={styles.detailRow}>
          <Ionicons name="location" size={16} color="#6b7280" />
          <Text style={styles.detailText}>{item.location}</Text>
        </View>
        
        <View style={styles.detailRow}>
          <Ionicons name="business" size={16} color="#6b7280" />
          <Text style={styles.detailText}>{item.highway_authority}</Text>
        </View>

        <View style={styles.detailRow}>
          <Ionicons name="shield" size={16} color="#6b7280" />
          <Text style={styles.detailText}>Proximity Risk Assessment: </Text>
          <View style={[styles.riskBadge, { backgroundColor: getRiskAssessmentColor(item.proximity_risk_assessment) }]}>
            <Text style={styles.riskText}>{item.proximity_risk_assessment}</Text>
          </View>
        </View>
        
        <TouchableOpacity 
          style={styles.coordinatesRow}
          onPress={() => openGoogleMaps(item.latitude, item.longitude)}
          activeOpacity={0.7}
        >
          <Ionicons name="map" size={16} color="#2563eb" />
          <Text style={styles.coordinatesText}>
            {item.latitude.toFixed(6)}, {item.longitude.toFixed(6)}
          </Text>
          <Ionicons name="external-link" size={14} color="#2563eb" />
        </TouchableOpacity>
      </View>
      
      <View style={styles.cardFooter}>
        <Text style={styles.addressText}>{item.address}</Text>
        <View style={styles.footerRight}>
          {item.inspection_status === 'completed' ? (
            <View style={styles.completedBadge}>
              <Ionicons name="checkmark-circle" size={16} color="#10b981" />
              <Text style={styles.completedText}>Inspected</Text>
            </View>
          ) : (
            <View style={styles.pendingBadge}>
              <Ionicons name="time" size={16} color="#f59e0b" />
              <Text style={styles.pendingText}>Pending</Text>
            </View>
          )}
          <Ionicons name="chevron-forward" size={20} color="#9ca3af" />
        </View>
      </View>
    </TouchableOpacity>
  );

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'active':
        return '#10b981';
      case 'pending':
        return '#f59e0b';
      case 'completed':
        return '#6b7280';
      default:
        return '#ef4444';
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading permits...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Permits</Text>
          <Text style={styles.subtitle}>
            Welcome back, {user?.username || 'User'}
          </Text>
        </View>
        <TouchableOpacity onPress={handleLogout} style={styles.logoutButton}>
          <Ionicons name="log-out-outline" size={24} color="#ef4444" />
        </TouchableOpacity>
      </View>

      <View style={styles.searchContainer}>
        <View style={styles.searchInputContainer}>
          <Ionicons name="search" size={20} color="#6b7280" style={styles.searchIcon} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search permit references (e.g., HAW, K6004...)"
            placeholderTextColor="#9ca3af"
            value={searchQuery}
            onChangeText={handleSearch}
            autoCapitalize="none"
            autoCorrect={false}
          />
          {searchQuery.length > 0 && (
            <TouchableOpacity 
              onPress={() => handleSearch('')}
              style={styles.clearButton}
            >
              <Ionicons name="close-circle" size={20} color="#6b7280" />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {permits.length === 0 ? (
        <View style={styles.emptyContainer}>
          <Ionicons name="document-text-outline" size={64} color="#9ca3af" />
          <Text style={styles.emptyTitle}>No Permits Found</Text>
          <Text style={styles.emptyText}>
            You don't have any permits assigned to you yet.
          </Text>
        </View>
      ) : (
        <FlatList
          data={filteredPermits}
          renderItem={renderPermitCard}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContainer}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor="#2563eb"
            />
          }
          showsVerticalScrollIndicator={false}
        />
      )}
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
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  subtitle: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  logoutButton: {
    padding: 8,
  },
  listContainer: {
    padding: 16,
  },
  permitCard: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  permitNumber: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    flex: 1,
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
  cardContent: {
    marginBottom: 12,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  detailText: {
    marginLeft: 8,
    fontSize: 14,
    color: '#374151',
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#e5e7eb',
  },
  addressText: {
    fontSize: 13,
    color: '#6b7280',
    flex: 1,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#374151',
    marginTop: 16,
    marginBottom: 8,
  },
  emptyText: {
    fontSize: 16,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 24,
  },
  headerLeft: {
    flex: 1,
  },
  headerRight: {
    alignItems: 'flex-end',
  },
  permitName: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  inspectionResults: {
    flexDirection: 'row',
    marginTop: 4,
  },
  resultBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    marginLeft: 4,
  },
  resultText: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '600',
  },
  riskBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
  },
  riskText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  coordinatesRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  coordinatesText: {
    marginLeft: 8,
    marginRight: 4,
    fontSize: 14,
    color: '#2563eb',
    textDecorationLine: 'underline',
  },
  footerRight: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  completedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
  },
  completedText: {
    marginLeft: 4,
    fontSize: 12,
    color: '#10b981',
    fontWeight: '600',
  },
  pendingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
  },
  pendingText: {
    marginLeft: 4,
    fontSize: 12,
    color: '#f59e0b',
    fontWeight: '600',
  },
});