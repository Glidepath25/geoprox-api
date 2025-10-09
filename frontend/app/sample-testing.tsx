import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Image,
  ActivityIndicator,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';

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
  proximity_risk_assessment: string;
}

export default function SampleTestingScreen() {
  const router = useRouter();
  const { permitId } = useLocalSearchParams();
  
  const [permit, setPermit] = useState<Permit | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  
  // Form fields
  const [sampleStatus, setSampleStatus] = useState('Pending sample');
  const [samplingDate, setSamplingDate] = useState(new Date().toISOString().split('T')[0]);
  const [resultsRecordedBy, setResultsRecordedBy] = useState('');
  const [sampledBy, setSampledBy] = useState('');
  const [notes, setNotes] = useState('');
  const [comments, setComments] = useState('');
  
  // Sample 1 details
  const [sample1Number, setSample1Number] = useState('');
  const [sample1Material, setSample1Material] = useState('');
  const [sample1LabAnalysis, setSample1LabAnalysis] = useState('');
  
  // Sample 2 details
  const [sample2Number, setSample2Number] = useState('');
  const [sample2Material, setSample2Material] = useState('');
  const [sample2LabAnalysis, setSample2LabAnalysis] = useState('');
  
  // Determinant results
  const [coalTarSample1, setCoalTarSample1] = useState('');
  const [coalTarSample2, setCoalTarSample2] = useState('');
  const [petroleumSample1, setPetroleumSample1] = useState('');
  const [petroleumSample2, setPetroleumSample2] = useState('');
  const [heavyMetalSample1, setHeavyMetalSample1] = useState('');
  const [heavyMetalSample2, setHeavyMetalSample2] = useState('');
  const [asbestosSample1, setAsbestosSample1] = useState('');
  const [asbestosSample2, setAsbestosSample2] = useState('');
  const [otherSample1, setOtherSample1] = useState('');
  const [otherSample2, setOtherSample2] = useState('');
  
  // Concentration values
  const [coalTarConc1, setCoalTarConc1] = useState('');
  const [coalTarConc2, setCoalTarConc2] = useState('');
  const [petroleumConc1, setPetroleumConc1] = useState('');
  const [petroleumConc2, setPetroleumConc2] = useState('');
  const [heavyMetalConc1, setHeavyMetalConc1] = useState('');
  const [heavyMetalConc2, setHeavyMetalConc2] = useState('');
  const [asbestosConc1, setAsbestosConc1] = useState('');
  const [asbestosConc2, setAsbestosConc2] = useState('');
  const [otherConc1, setOtherConc1] = useState('');
  const [otherConc2, setOtherConc2] = useState('');
  
  // Attachments
  const [fieldPhotos, setFieldPhotos] = useState<string[]>([]);
  const [labResults, setLabResults] = useState<string[]>([]);
  const [generalAttachments, setGeneralAttachments] = useState<string[]>([]);

  useEffect(() => {
    loadPermit();
    loadExistingSampleTest();
    requestPermissions();
  }, []);

  const requestPermissions = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Sorry, we need camera roll permissions to add photos.');
    }
  };

  const loadPermit = async () => {
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

  const loadExistingSampleTest = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      
      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/sample-testing/current/${permitId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const sampleTest = await response.json();
        if (sampleTest) {
          // Populate form fields with existing data
          setSampleStatus(sampleTest.sample_status || 'Pending sample');
          setSamplingDate(sampleTest.sampling_date ? new Date(sampleTest.sampling_date).toISOString().split('T')[0] : new Date().toISOString().split('T')[0]);
          setResultsRecordedBy(sampleTest.results_recorded_by || '');
          setSampledBy(sampleTest.sampled_by || '');
          setNotes(sampleTest.notes || '');
          setComments(sampleTest.comments || '');
          
          // Sample details
          setSample1Number(sampleTest.sample1_number || '');
          setSample1Material(sampleTest.sample1_material || '');
          setSample1LabAnalysis(sampleTest.sample1_lab_analysis || '');
          setSample2Number(sampleTest.sample2_number || '');
          setSample2Material(sampleTest.sample2_material || '');
          setSample2LabAnalysis(sampleTest.sample2_lab_analysis || '');
          
          // Determinants
          setCoalTarSample1(sampleTest.coal_tar_sample1 || '');
          setCoalTarSample2(sampleTest.coal_tar_sample2 || '');
          setPetroleumSample1(sampleTest.petroleum_sample1 || '');
          setPetroleumSample2(sampleTest.petroleum_sample2 || '');
          setHeavyMetalSample1(sampleTest.heavy_metal_sample1 || '');
          setHeavyMetalSample2(sampleTest.heavy_metal_sample2 || '');
          setAsbestosSample1(sampleTest.asbestos_sample1 || '');
          setAsbestosSample2(sampleTest.asbestos_sample2 || '');
          setOtherSample1(sampleTest.other_sample1 || '');
          setOtherSample2(sampleTest.other_sample2 || '');
          
          // Concentrations
          setCoalTarConc1(sampleTest.coal_tar_conc1 || '');
          setCoalTarConc2(sampleTest.coal_tar_conc2 || '');
          setPetroleumConc1(sampleTest.petroleum_conc1 || '');
          setPetroleumConc2(sampleTest.petroleum_conc2 || '');
          setHeavyMetalConc1(sampleTest.heavy_metal_conc1 || '');
          setHeavyMetalConc2(sampleTest.heavy_metal_conc2 || '');
          setAsbestosConc1(sampleTest.asbestos_conc1 || '');
          setAsbestosConc2(sampleTest.asbestos_conc2 || '');
          setOtherConc1(sampleTest.other_conc1 || '');
          setOtherConc2(sampleTest.other_conc2 || '');
          
          // Attachments
          setFieldPhotos(sampleTest.field_photos || []);
          setLabResults(sampleTest.lab_results || []);
          setGeneralAttachments(sampleTest.general_attachments || []);
          
          console.log('Loaded existing sample test data');
        }
      }
    } catch (error) {
      console.log('No existing sample test found or error loading:', error);
    }
  };

  const addAttachment = async (type: 'field' | 'lab' | 'general') => {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        aspect: [4, 3],
        quality: 0.8,
        base64: true,
      });

      if (!result.canceled && result.assets[0].base64) {
        const base64Image = `data:image/jpeg;base64,${result.assets[0].base64}`;
        
        switch (type) {
          case 'field':
            setFieldPhotos(prev => [...prev, base64Image]);
            break;
          case 'lab':
            setLabResults(prev => [...prev, base64Image]);
            break;
          case 'general':
            setGeneralAttachments(prev => [...prev, base64Image]);
            break;
        }
      }
    } catch (error) {
      console.error('Attachment error:', error);
      Alert.alert('Error', 'Failed to add attachment');
    }
  };

  const removeAttachment = (type: 'field' | 'lab' | 'general', index: number) => {
    Alert.alert(
      'Remove Attachment',
      'Are you sure you want to remove this attachment?',
      [
        { text: 'Cancel', style: 'cancel' },
        { 
          text: 'Remove', 
          style: 'destructive',
          onPress: () => {
            switch (type) {
              case 'field':
                setFieldPhotos(prev => prev.filter((_, i) => i !== index));
                break;
              case 'lab':
                setLabResults(prev => prev.filter((_, i) => i !== index));
                break;
              case 'general':
                setGeneralAttachments(prev => prev.filter((_, i) => i !== index));
                break;
            }
          }
        },
      ]
    );
  };

  const validateForm = () => {
    const missingFields = [];
    
    if (!resultsRecordedBy.trim()) {
      missingFields.push('Results recorded by');
    }

    if (!sampledBy.trim()) {
      missingFields.push('Sampled by');
    }

    if (missingFields.length > 0) {
      Alert.alert(
        'Submission Failed', 
        `Please complete the following mandatory fields:\n\n• ${missingFields.join('\n• ')}`,
        [{ text: 'OK', style: 'default' }]
      );
      return false;
    }

    return true;
  };

  const saveSampleTest = async () => {
    setSaving(true);
    try {
      const token = await AsyncStorage.getItem('token');
      
      const sampleData = {
        permit_id: permitId,
        sample_status: sampleStatus,
        sampling_date: samplingDate,
        results_recorded_by: resultsRecordedBy,
        sampled_by: sampledBy,
        notes: notes,
        comments: comments,
        sample1_number: sample1Number,
        sample1_material: sample1Material,
        sample1_lab_analysis: sample1LabAnalysis,
        sample2_number: sample2Number,
        sample2_material: sample2Material,
        sample2_lab_analysis: sample2LabAnalysis,
        coal_tar_sample1: coalTarSample1,
        coal_tar_sample2: coalTarSample2,
        petroleum_sample1: petroleumSample1,
        petroleum_sample2: petroleumSample2,
        heavy_metal_sample1: heavyMetalSample1,
        heavy_metal_sample2: heavyMetalSample2,
        asbestos_sample1: asbestosSample1,
        asbestos_sample2: asbestosSample2,
        other_sample1: otherSample1,
        other_sample2: otherSample2,
        coal_tar_conc1: coalTarConc1,
        coal_tar_conc2: coalTarConc2,
        petroleum_conc1: petroleumConc1,
        petroleum_conc2: petroleumConc2,
        heavy_metal_conc1: heavyMetalConc1,
        heavy_metal_conc2: heavyMetalConc2,
        asbestos_conc1: asbestosConc1,
        asbestos_conc2: asbestosConc2,
        other_conc1: otherConc1,
        other_conc2: otherConc2,
        field_photos: fieldPhotos,
        lab_results: labResults,
        general_attachments: generalAttachments,
      };

      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/sample-testing/save`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sampleData),
      });

      if (response.ok) {
        Alert.alert('Saved', 'Sample testing saved as draft. You can complete it later.');
      } else {
        const errorData = await response.json();
        Alert.alert('Error', errorData.detail || 'Failed to save sample testing');
      }
    } catch (error) {
      console.error('Save error:', error);
      Alert.alert('Error', 'Network error saving sample testing');
    } finally {
      setSaving(false);
    }
  };

  const submitSampleTest = async () => {
    if (!validateForm()) return;

    setSubmitting(true);
    try {
      const token = await AsyncStorage.getItem('token');
      
      const sampleData = {
        permit_id: permitId,
        sample_status: sampleStatus,
        sampling_date: samplingDate,
        results_recorded_by: resultsRecordedBy,
        sampled_by: sampledBy,
        notes: notes,
        comments: comments,
        sample1_number: sample1Number,
        sample1_material: sample1Material,
        sample1_lab_analysis: sample1LabAnalysis,
        sample2_number: sample2Number,
        sample2_material: sample2Material,
        sample2_lab_analysis: sample2LabAnalysis,
        coal_tar_sample1: coalTarSample1,
        coal_tar_sample2: coalTarSample2,
        petroleum_sample1: petroleumSample1,
        petroleum_sample2: petroleumSample2,
        heavy_metal_sample1: heavyMetalSample1,
        heavy_metal_sample2: heavyMetalSample2,
        asbestos_sample1: asbestosSample1,
        asbestos_sample2: asbestosSample2,
        other_sample1: otherSample1,
        other_sample2: otherSample2,
        coal_tar_conc1: coalTarConc1,
        coal_tar_conc2: coalTarConc2,
        petroleum_conc1: petroleumConc1,
        petroleum_conc2: petroleumConc2,
        heavy_metal_conc1: heavyMetalConc1,
        heavy_metal_conc2: heavyMetalConc2,
        asbestos_conc1: asbestosConc1,
        asbestos_conc2: asbestosConc2,
        other_conc1: otherConc1,
        other_conc2: otherConc2,
        field_photos: fieldPhotos,
        lab_results: labResults,
        general_attachments: generalAttachments,
      };

      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/sample-testing/submit`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sampleData),
      });

      if (response.ok) {
        Alert.alert(
          'Sample Testing Submitted',
          'Sample testing has been successfully submitted and marked as complete.',
          [{ text: 'OK', onPress: () => router.back() }]
        );
      } else {
        const errorData = await response.json();
        Alert.alert('Error', errorData.detail || 'Failed to submit sample testing');
      }
    } catch (error) {
      console.error('Submit error:', error);
      Alert.alert('Error', 'Network error submitting sample testing');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading permit...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
            <Ionicons name="arrow-back" size={24} color="#2563eb" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Sample Testing</Text>
          <View style={styles.placeholder} />
        </View>

        <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
          {/* Permit Details */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Permit details</Text>
            
            <View style={styles.detailsGrid}>
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>PERMIT NUMBER</Text>
                <Text style={styles.detailValue}>{permit?.permit_number}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>DATE OF TESTING</Text>
                <Text style={styles.detailValue}>{new Date().toISOString().split('T')[0]}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>LOCATION OF WORK</Text>
                <Text style={styles.detailValue}>{permit?.location}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>PROXIMITY RISK ASSESSMENT</Text>
                <Text style={styles.detailValue}>{permit?.proximity_risk_assessment}</Text>
              </View>
            </View>
          </View>

          {/* Sample Information */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Sample Information</Text>
            
            <View style={styles.inputRow}>
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>SAMPLE STATUS</Text>
                <TextInput
                  style={styles.input}
                  value={sampleStatus}
                  onChangeText={setSampleStatus}
                  placeholder="Pending sample"
                />
              </View>
              
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>SAMPLING DATE</Text>
                <TextInput
                  style={styles.input}
                  value={samplingDate}
                  onChangeText={setSamplingDate}
                  placeholder="YYYY-MM-DD"
                />
              </View>
            </View>

            <View style={styles.inputRow}>
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>RESULTS RECORDED BY *</Text>
                <TextInput
                  style={styles.input}
                  value={resultsRecordedBy}
                  onChangeText={setResultsRecordedBy}
                  placeholder="Enter name"
                />
              </View>
              
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>SAMPLED BY *</Text>
                <TextInput
                  style={styles.input}
                  value={sampledBy}
                  onChangeText={setSampledBy}
                  placeholder="Enter name"
                />
              </View>
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>NOTES</Text>
              <TextInput
                style={[styles.input, styles.textArea]}
                value={notes}
                onChangeText={setNotes}
                placeholder="Enter notes"
                multiline
                numberOfLines={3}
              />
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>COMMENTS</Text>
              <TextInput
                style={[styles.input, styles.textArea]}
                value={comments}
                onChangeText={setComments}
                placeholder="Enter comments"
                multiline
                numberOfLines={3}
              />
            </View>
          </View>

          {/* Sample Details */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Sample Details</Text>
            
            <Text style={styles.subsectionTitle}>Sample 1</Text>
            <View style={styles.inputRow}>
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>SAMPLE NUMBER</Text>
                <TextInput
                  style={styles.input}
                  value={sample1Number}
                  onChangeText={setSample1Number}
                  placeholder="Enter sample number"
                />
              </View>
              
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>MATERIAL SAMPLED</Text>
                <View style={styles.radioGroup}>
                  <TouchableOpacity
                    style={[styles.radioOption, sample1Material === 'Bituminous' && styles.radioSelected]}
                    onPress={() => setSample1Material('Bituminous')}
                  >
                    <Text style={[styles.radioText, sample1Material === 'Bituminous' && styles.radioTextSelected]}>
                      Bituminous
                    </Text>
                  </TouchableOpacity>
                  
                  <TouchableOpacity
                    style={[styles.radioOption, sample1Material === 'Sub-base' && styles.radioSelected]}
                    onPress={() => setSample1Material('Sub-base')}
                  >
                    <Text style={[styles.radioText, sample1Material === 'Sub-base' && styles.radioTextSelected]}>
                      Sub-base
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
            
            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>LAB ANALYSIS</Text>
              <View style={styles.radioGroup}>
                <TouchableOpacity
                  style={[styles.radioOption, sample1LabAnalysis === 'Green' && styles.radioSelected]}
                  onPress={() => setSample1LabAnalysis('Green')}
                >
                  <Text style={[styles.radioText, sample1LabAnalysis === 'Green' && styles.radioTextSelected]}>
                    Green
                  </Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[styles.radioOption, sample1LabAnalysis === 'Red' && styles.radioSelected]}
                  onPress={() => setSample1LabAnalysis('Red')}
                >
                  <Text style={[styles.radioText, sample1LabAnalysis === 'Red' && styles.radioTextSelected]}>
                    Red
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            <Text style={styles.subsectionTitle}>Sample 2</Text>
            <View style={styles.inputRow}>
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>SAMPLE NUMBER</Text>
                <TextInput
                  style={styles.input}
                  value={sample2Number}
                  onChangeText={setSample2Number}
                  placeholder="Enter sample number"
                />
              </View>
              
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>MATERIAL SAMPLED</Text>
                <View style={styles.radioGroup}>
                  <TouchableOpacity
                    style={[styles.radioOption, sample2Material === 'Bituminous' && styles.radioSelected]}
                    onPress={() => setSample2Material('Bituminous')}
                  >
                    <Text style={[styles.radioText, sample2Material === 'Bituminous' && styles.radioTextSelected]}>
                      Bituminous
                    </Text>
                  </TouchableOpacity>
                  
                  <TouchableOpacity
                    style={[styles.radioOption, sample2Material === 'Sub-base' && styles.radioSelected]}
                    onPress={() => setSample2Material('Sub-base')}
                  >
                    <Text style={[styles.radioText, sample2Material === 'Sub-base' && styles.radioTextSelected]}>
                      Sub-base
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
            
            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>LAB ANALYSIS</Text>
              <View style={styles.radioGroup}>
                <TouchableOpacity
                  style={[styles.radioOption, sample2LabAnalysis === 'Green' && styles.radioSelected]}
                  onPress={() => setSample2LabAnalysis('Green')}
                >
                  <Text style={[styles.radioText, sample2LabAnalysis === 'Green' && styles.radioTextSelected]}>
                    Green
                  </Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[styles.radioOption, sample2LabAnalysis === 'Red' && styles.radioSelected]}
                  onPress={() => setSample2LabAnalysis('Red')}
                >
                  <Text style={[styles.radioText, sample2LabAnalysis === 'Red' && styles.radioTextSelected]}>
                    Red
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>

          {/* Determinant Results */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Determinant Results</Text>
            
            {/* Coal Tar */}
            <Text style={styles.subsectionTitle}>Coal tar</Text>
            <View style={styles.resultsRow}>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 1</Text>
                <TextInput
                  style={styles.input}
                  value={coalTarSample1}
                  onChangeText={setCoalTarSample1}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 1</Text>
                <TextInput
                  style={styles.input}
                  value={coalTarConc1}
                  onChangeText={setCoalTarConc1}
                  placeholder="mg/kg"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 2</Text>
                <TextInput
                  style={styles.input}
                  value={coalTarSample2}
                  onChangeText={setCoalTarSample2}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 2</Text>
                <TextInput
                  style={styles.input}
                  value={coalTarConc2}
                  onChangeText={setCoalTarConc2}
                  placeholder="mg/kg"
                />
              </View>
            </View>

            {/* Petroleum */}
            <Text style={styles.subsectionTitle}>Petroleum</Text>
            <View style={styles.resultsRow}>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 1</Text>
                <TextInput
                  style={styles.input}
                  value={petroleumSample1}
                  onChangeText={setPetroleumSample1}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 1</Text>
                <TextInput
                  style={styles.input}
                  value={petroleumConc1}
                  onChangeText={setPetroleumConc1}
                  placeholder="mg/kg"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 2</Text>
                <TextInput
                  style={styles.input}
                  value={petroleumSample2}
                  onChangeText={setPetroleumSample2}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 2</Text>
                <TextInput
                  style={styles.input}
                  value={petroleumConc2}
                  onChangeText={setPetroleumConc2}
                  placeholder="mg/kg"
                />
              </View>
            </View>

            {/* Heavy Metal */}
            <Text style={styles.subsectionTitle}>Heavy metal</Text>
            <View style={styles.resultsRow}>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 1</Text>
                <TextInput
                  style={styles.input}
                  value={heavyMetalSample1}
                  onChangeText={setHeavyMetalSample1}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 1</Text>
                <TextInput
                  style={styles.input}
                  value={heavyMetalConc1}
                  onChangeText={setHeavyMetalConc1}
                  placeholder="mg/kg"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 2</Text>
                <TextInput
                  style={styles.input}
                  value={heavyMetalSample2}
                  onChangeText={setHeavyMetalSample2}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 2</Text>
                <TextInput
                  style={styles.input}
                  value={heavyMetalConc2}
                  onChangeText={setHeavyMetalConc2}
                  placeholder="mg/kg"
                />
              </View>
            </View>

            {/* Asbestos */}
            <Text style={styles.subsectionTitle}>Asbestos</Text>
            <View style={styles.resultsRow}>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 1</Text>
                <TextInput
                  style={styles.input}
                  value={asbestosSample1}
                  onChangeText={setAsbestosSample1}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 1</Text>
                <TextInput
                  style={styles.input}
                  value={asbestosConc1}
                  onChangeText={setAsbestosConc1}
                  placeholder="mg/kg"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 2</Text>
                <TextInput
                  style={styles.input}
                  value={asbestosSample2}
                  onChangeText={setAsbestosSample2}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 2</Text>
                <TextInput
                  style={styles.input}
                  value={asbestosConc2}
                  onChangeText={setAsbestosConc2}
                  placeholder="mg/kg"
                />
              </View>
            </View>

            {/* Other */}
            <Text style={styles.subsectionTitle}>Other</Text>
            <View style={styles.resultsRow}>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 1</Text>
                <TextInput
                  style={styles.input}
                  value={otherSample1}
                  onChangeText={setOtherSample1}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 1</Text>
                <TextInput
                  style={styles.input}
                  value={otherConc1}
                  onChangeText={setOtherConc1}
                  placeholder="mg/kg"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>SAMPLE 2</Text>
                <TextInput
                  style={styles.input}
                  value={otherSample2}
                  onChangeText={setOtherSample2}
                  placeholder="Result"
                />
              </View>
              <View style={styles.resultInputContainer}>
                <Text style={styles.inputLabel}>CONCENTRATION 2</Text>
                <TextInput
                  style={styles.input}
                  value={otherConc2}
                  onChangeText={setOtherConc2}
                  placeholder="mg/kg"
                />
              </View>
            </View>
          </View>

          {/* Attachments */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Attachments</Text>
            
            {/* Field Photos */}
            <View style={styles.attachmentSection}>
              <View style={styles.attachmentHeader}>
                <Text style={styles.attachmentTitle}>Field Photos</Text>
                <TouchableOpacity onPress={() => addAttachment('field')} style={styles.addButton}>
                  <Ionicons name="camera" size={16} color="#2563eb" />
                  <Text style={styles.addButtonText}>Add Photo</Text>
                </TouchableOpacity>
              </View>
              
              {fieldPhotos.length === 0 ? (
                <Text style={styles.noAttachments}>No field photos added</Text>
              ) : (
                <View style={styles.attachmentsGrid}>
                  {fieldPhotos.map((photo, index) => (
                    <View key={index} style={styles.attachmentContainer}>
                      <Image source={{ uri: photo }} style={styles.attachment} />
                      <TouchableOpacity
                        onPress={() => removeAttachment('field', index)}
                        style={styles.removeButton}
                      >
                        <Ionicons name="close-circle" size={20} color="#ef4444" />
                      </TouchableOpacity>
                    </View>
                  ))}
                </View>
              )}
            </View>

            {/* Lab Results */}
            <View style={styles.attachmentSection}>
              <View style={styles.attachmentHeader}>
                <Text style={styles.attachmentTitle}>Lab Results</Text>
                <TouchableOpacity onPress={() => addAttachment('lab')} style={styles.addButton}>
                  <Ionicons name="document" size={16} color="#2563eb" />
                  <Text style={styles.addButtonText}>Add Document</Text>
                </TouchableOpacity>
              </View>
              
              {labResults.length === 0 ? (
                <Text style={styles.noAttachments}>No lab results added</Text>
              ) : (
                <View style={styles.attachmentsGrid}>
                  {labResults.map((doc, index) => (
                    <View key={index} style={styles.attachmentContainer}>
                      <Image source={{ uri: doc }} style={styles.attachment} />
                      <TouchableOpacity
                        onPress={() => removeAttachment('lab', index)}
                        style={styles.removeButton}
                      >
                        <Ionicons name="close-circle" size={20} color="#ef4444" />
                      </TouchableOpacity>
                    </View>
                  ))}
                </View>
              )}
            </View>

            {/* General Attachments */}
            <View style={styles.attachmentSection}>
              <View style={styles.attachmentHeader}>
                <Text style={styles.attachmentTitle}>General Attachments</Text>
                <TouchableOpacity onPress={() => addAttachment('general')} style={styles.addButton}>
                  <Ionicons name="attach" size={16} color="#2563eb" />
                  <Text style={styles.addButtonText}>Add File</Text>
                </TouchableOpacity>
              </View>
              
              {generalAttachments.length === 0 ? (
                <Text style={styles.noAttachments}>No general attachments added</Text>
              ) : (
                <View style={styles.attachmentsGrid}>
                  {generalAttachments.map((file, index) => (
                    <View key={index} style={styles.attachmentContainer}>
                      <Image source={{ uri: file }} style={styles.attachment} />
                      <TouchableOpacity
                        onPress={() => removeAttachment('general', index)}
                        style={styles.removeButton}
                      >
                        <Ionicons name="close-circle" size={20} color="#ef4444" />
                      </TouchableOpacity>
                    </View>
                  ))}
                </View>
              )}
            </View>
          </View>

          {/* Submit Buttons */}
          <View style={styles.submitSection}>
            <View style={styles.buttonsContainer}>
              <TouchableOpacity
                style={[styles.saveButton, saving && styles.buttonDisabled]}
                onPress={saveSampleTest}
                disabled={saving || submitting}
              >
                {saving ? (
                  <ActivityIndicator size="small" color="#2563eb" />
                ) : (
                  <>
                    <Ionicons name="save-outline" size={20} color="#2563eb" />
                    <Text style={styles.saveButtonText}>Save Draft</Text>
                  </>
                )}
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.submitButton, submitting && styles.buttonDisabled]}
                onPress={submitSampleTest}
                disabled={submitting || saving}
              >
                {submitting ? (
                  <ActivityIndicator size="small" color="#ffffff" />
                ) : (
                  <>
                    <Ionicons name="checkmark-circle" size={20} color="#ffffff" />
                    <Text style={styles.submitButtonText}>Submit Final</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  keyboardView: {
    flex: 1,
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
  backButton: {
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
    marginBottom: 16,
  },
  subsectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
    marginTop: 16,
    marginBottom: 12,
  },
  detailsGrid: {
    marginBottom: 16,
  },
  detailItem: {
    marginBottom: 12,
  },
  detailLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6b7280',
    marginBottom: 4,
    letterSpacing: 0.5,
  },
  detailValue: {
    fontSize: 16,
    color: '#1f2937',
  },
  inputRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  inputContainer: {
    flex: 1,
    marginRight: 8,
  },
  inputLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6b7280',
    marginBottom: 6,
    letterSpacing: 0.5,
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
    backgroundColor: '#f9fafb',
    color: '#1f2937',
  },
  textArea: {
    height: 80,
    textAlignVertical: 'top',
  },
  resultsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginBottom: 16,
  },
  resultInputContainer: {
    width: '48%',
    marginRight: '2%',
    marginBottom: 12,
  },
  attachmentSection: {
    marginTop: 16,
  },
  attachmentHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  attachmentTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
  },
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#eff6ff',
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
  },
  addButtonText: {
    marginLeft: 4,
    fontSize: 12,
    fontWeight: '600',
    color: '#2563eb',
  },
  noAttachments: {
    fontSize: 14,
    color: '#9ca3af',
    fontStyle: 'italic',
    paddingVertical: 16,
    textAlign: 'center',
  },
  attachmentsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  attachmentContainer: {
    position: 'relative',
    marginRight: 12,
    marginBottom: 12,
  },
  attachment: {
    width: 60,
    height: 60,
    borderRadius: 6,
  },
  removeButton: {
    position: 'absolute',
    top: -6,
    right: -6,
    backgroundColor: '#ffffff',
    borderRadius: 10,
  },
  submitSection: {
    padding: 16,
    marginBottom: 32,
  },
  buttonsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  saveButton: {
    flex: 1,
    backgroundColor: '#ffffff',
    borderWidth: 2,
    borderColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButtonText: {
    color: '#2563eb',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
  submitButton: {
    flex: 1,
    backgroundColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  submitButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  radioGroup: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  radioOption: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 6,
    marginRight: 12,
    backgroundColor: '#ffffff',
  },
  radioSelected: {
    backgroundColor: '#2563eb',
    borderColor: '#2563eb',
  },
  radioText: {
    fontSize: 14,
    color: '#374151',
  },
  radioTextSelected: {
    color: '#ffffff',
  },
});