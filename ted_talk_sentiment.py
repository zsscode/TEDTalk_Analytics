import re
import os
import cPickle as cp
import numpy as np
from itertools import product
from scipy.stats import ttest_ind
import matplotlib.pyplot as plt
from nltk.tokenize import sent_tokenize
from bluemix import parse_sentence_tone
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

'''
Dict of talks with highest view count and Lowest view counts
Note, while calculating the lowest view counts, I took only
the talks that are at least two years old (i.e. retention time
is greater than 730 days). This is done to ignore the very new
talks
'''
hi_lo_files = {
            'High_View_Talks':[66,96,97,206,229,549,618,
                685,741,848,1246,1344,1377,1569,1647,1815,1821,
                2034,2399,2405],
            'Low_View_Talks':[220,268,339,345,379,402,403,427,
                439,500,673,675,679,925,962,1294,1332,1373,
                1445,1466]
               }

############################### Generic Readers ##############################
'''
These functions (generic readers) go to the input of sentiment comparator
class as preset values of the "redear" variable. All these functions follow
the same input-output convention. The input is the fullpath of a pickle 
file containing the talk transcript and meta data. The output is a list
containing the transcripts in a specific format
'''
def read_sentences(pklfile):
    '''
    Read talk transcripts and tokenize the sentences
    While tokenizing, it removes sound tags: (Applause), (Laughter) etc.    
    '''
    assert os.path.isfile(pklfile),'File not found: '+pklfile
    data = cp.load(open(pklfile))
    txt = re.sub('\([a-zA-Z]*?\)','',' '.join(data['talk_transcript']))
    return sent_tokenize(txt)

def read_utterances(pklfile):
    '''
    Similar to read_sentences, but returns utterances instead
    utternaces is the ways transcripts are written in the pickle file
    '''
    assert os.path.isfile(pklfile),'File not found: '+pklfile
    data = cp.load(open(pklfile))
    txt = re.sub('\([a-zA-Z]*?\)','','__||__'.join(data['talk_transcript']))
    return txt.split('__||__')

def read_bluemix(pklfile,sentiment_dir='./bluemix_sentiment/'):
    '''
    Reads all the sentences and their corresponding bluemix sentiments.
    Note: DONOT change the name of this function. It is used somewhere
    else in the code
    '''
    assert os.path.isfile(pklfile),'File not found: '+pklfile
    pklfile = sentiment_dir+pklfile.split('/')[-1]
    assert os.path.isfile(pklfile),'Sentiment file not found: '+pklfile+\
        ' \nCheck the sentiment_dir argument'
    data = cp.load(open(pklfile))
    assert data.get('sentences_tone'), \
        'Sentence-wise sentiment is not available: {0}'.format(pklfile)
    scores,header,sentences,_,_ = parse_sentence_tone(data['sentences_tone'])
    return scores,header,sentences
########################### End of Generic Readers ###########################

######################### Sentiment Extractors ###############################
# These functions go to the input of sentiment comparator class as preset
# values of the variable "extractor". By default, use vadersentiment.
# the functions take a sentence to calculate sentiment and outputs two lists.
# The first one is a list of sentiments, the second list is the names of the
# corresponding sentiment.
analyzer = SentimentIntensityAnalyzer()
def vadersentiment(asent):
    results = analyzer.polarity_scores(asent)
    return [results['neg'],results['neu'],results['pos'],results['compound']],\
    ['negative','neutral','positive','compound']
##############################################################################

class Sentiment_Comparator(object):
    '''
    Sentiment Comparator class contains all the information to compare
    sentiment data between several groups of files.
    It performs the following major tasks. Given the ids of talks for a number of
    groups, it extracts the raw sentiments values for each sentence or utterances
    of a talk, smoothens the time-series formed by those raw sentiment values and
    then interpolates the time-series to a common length (100 sample). This data
    is preserved within the class so that it can be possible to see the time
    averages or ensemble averages of the time-series. It also stores the backward
    references to the original sentences after the interpolation, so that it is
    possible to find from which sentences the interpolated samples are derived.

    It contains the following inputs and variables:
    groups        : Input dictionary with group name as keys and the talk indices
                    as values
    reader        : reader takes a function to read the transcripts of the talk.
                    It can take either the read_sentences function
                    or the read_utterances -- indicating that the transcriptions
                    would be read sentence by sentence or utterance by utterance
                    Note that bluemix reader works little differently than the
                    other readers. It (bluemix) extracts the sentiments while
                    reading the sentences.
    extractor     : If the reader is chosen anything other than bluemix reader,
                    then we should also specify a sentiment extractor (extractor).
                    The extractor variable takes a function. The job of the 
                    extractor function is to take one sentence at a time and 
                    extract the sentiment as efficiently as possible. The 
                    function specifies the method of extracting sentiments.
                    The easiest way to extract sentiment is to use the 
                    vaderSentiment package. The vadersentiment()
                    function uses this package. Look into the Sentiment 
                    Extractors section.
    inputFolder   : Folder where the .pkl files reside
    raw_sentiments: A dictionary storing the raw sentiments.
                    The keys are the talk ids and values
                    are matrices for which columns represent sentiment as
                    mentioned in the column_names variable
    column_names  : Name of columns of the sentiment matrix. For vadersentiment
                    it is ['neg','neu','pos']. This variable is populated
                    when loading the raw sentiments
    sentiments_intep: The sentiment data interpolated to a canonical size
    back_ref      : Reference to the old indices of the sentences from 
                    each interpolated sample
    alltalks      : List of all the talk ids being analyzed in this comparator
    '''
    def __init__(self,
                dict_groups,
                reader,
                extractor=vadersentiment,
                inputFolder='./talks/',
                process=True):
        self.inputpath=inputFolder
        self.reader = reader    
        self.extractor = extractor
        self.groups = dict_groups
        self.alltalks = [ids for agroup in self.groups \
            for ids in self.groups[agroup]]
        # The bluemix reader needs special treatment
        if self.reader.func_name=='read_bluemix':
            self.extractor = None
        
        self.raw_sentiments = {}
        self.sentiments_intep={}
        self.back_ref={}
        self.column_names=[]
        if process:
            self.extract_raw_sentiment()
            self.smoothen_raw_sentiment()
            self.intep_sentiment_series()

    # Fill out self.raw_sentiments
    def extract_raw_sentiment(self):
        for i,atalk in enumerate(self.alltalks):
            # The bluemix reader needs special treatment
            if self.reader.func_name=='read_bluemix':
                filename = self.inputpath+str(atalk)+'.pkl'
                scores,header,_ = self.reader(filename)
                if i==0:
                    self.column_names = header
                self.raw_sentiments[atalk] = scores
            else:
                sents = self.reader(self.inputpath+str(atalk)+'.pkl')
                values = []
                for asent in sents:
                    results,header=self.extractor(asent)
                    values.append(results)
                if i==0:
                    self.column_names = header
                self.raw_sentiments[atalk] = np.array(values)

    # Changes the self.raw_sentiments to a smoothed version
    def smoothen_raw_sentiment(self,kernelLen=5.):
        # Get number of columns in sentiment matrix 
        _,n = np.shape(self.raw_sentiments[self.alltalks[0]])

        for atalk in self.alltalks:
            for i in range(n):
                self.raw_sentiments[atalk][:,i] = np.convolve(\
                self.raw_sentiments[atalk][:,i],\
                np.ones(kernelLen)/float(kernelLen),mode='same')                    

    def intep_sentiment_series(self,bins=100):
        '''
        Fills out the variable self.sentiments_intep. Different sentiment
        series has different lengths due to the variable length of the talks.
        This function brings all the series in a common length (having 
        100 samples). It also updates the backward reference (back_ref)
        '''        
        for atalk in self.alltalks:
            m,n = np.shape(self.raw_sentiments[atalk])
            # Pre-allocate
            self.sentiments_intep[atalk] = np.zeros((bins,n))
            # x values for the interpolation
            old_xvals = np.arange(m)
            new_xvals = np.linspace(0,old_xvals[-1],num=bins)
            # Update the backward reference
            self.back_ref[atalk] = [np.where((old_xvals>=lo) & \
                (old_xvals<=hi))[0].tolist() for lo,hi in \
                zip(new_xvals[:-1],new_xvals[1:])]+[[old_xvals[-1]]]
            # Interpolate column by column
            for i in range(n):
                self.sentiments_intep[atalk][:,i] = \
                np.interp(new_xvals,old_xvals,self.raw_sentiments[atalk][:,i])

    # Calculates (and returns) the ensemble averages of the groups
    def calc_group_mean(self):
        group_average = {}
        for agroup in self.groups:
            vals = [self.sentiments_intep[id] for id in self.groups[agroup]]
            # Averaging over the talks in a group
            group_average[agroup]=np.mean(vals,axis=0)
        return group_average

    def calc_time_mean(self,perform_ttest=True):
        '''
        Calculates (and returns) the Time averages of the sentiments
        Also returns the p-values if ttest is done. Note: ttest can't
        be done for more than 2 groups
        '''
        time_avg = {}
        for agroup in self.groups:
            vals = [self.sentiments_intep[id] for id in self.groups[agroup]]
            # Averaging over time
            time_avg[agroup]=np.mean(vals,axis=1)
        # Perform ttest for statistical significance
        if perform_ttest:
            pvals=[]
            m,n = np.shape(time_avg[agroup])
            allkeys=time_avg.keys()
            assert len(allkeys)==2,'T-test can not be done for 2+ groups'
            for i in range(n):
                print 'Sentiment:',self.column_names[i],
                _,p = ttest_ind(time_avg[allkeys[0]][:,i],
                    time_avg[allkeys[1]][:,i])
                print 'p-value:',p
                pvals.append(p)
        # Average and return
        for agroup in time_avg:
            time_avg[agroup]=np.mean(time_avg[agroup],axis=0)
        if not perform_ttest:
            return time_avg
        else:
            return time_avg,pvals

    # Even though the sentiment plots are interpolated to 0 to 100
    # to calculate ensemble averages, the reference to the original
    # sentence is not lost. Every talk keeps a "backword reference"
    # indicating what are the original sentences (actually the sentence number)
    def display_sentences(self,talkid,start_percent,end_percent):
        pass

################################ Plotters ####################################
# Draws the sentiment values of a single talk. The input array
# can be either raw sentiments or interpolated sentiments
def draw_single_sentiment(anarray,outfilename=None):
    plt.figure()
    plt.plot(anarray)
    plt.tight_layout()
    plt.xlabel('Sentence Number')
    plt.ylabel('Values')
    plt.legend(['Negative','Neutral','Positive'])
    if outfilename:
        plt.savefig(outfilename)
    else:
        plt.show()

# Draws the ensemble averages of the sentiments
def draw_group_mean_sentiments(grp_means,
                            column_names,
                            styles,
                            outfilename=None):
    plt.figure()    
    for g,agroup in enumerate(grp_means):
        m,n = np.shape(grp_means[agroup])
        for col in range(n):
            plt.plot(grp_means[agroup][:,col],
                styles[g*len(column_names)+col],
                label=agroup+'_'+column_names[col])
        plt.xlabel('Interpolated Sentence Number')
        plt.ylabel('Values')
    plt.tight_layout()
    plt.legend(loc='center right')
    if outfilename:
        plt.savefig(outfilename)
    else:
        plt.show()

# Draw bar plots for time averages and annotate pvalues
def draw_time_mean_sentiments(time_avg,
                            column_names,
                            pvals,
                            groupcolor=['royalblue','darkkhaki'],
                            outfilename=None):
    plt.figure()
    for i,grp in enumerate(time_avg):
        plt.bar(np.arange(len(time_avg[grp]))-i*0.25,
                time_avg[grp],
                color=groupcolor[i],
                width = 0.25,
                label=grp)
    plt.tight_layout()
    plt.ylabel('Average Sentiment Value')
    plt.legend()
    ax = plt.gca()
    ax.set_xticks(np.arange(len(time_avg[grp])))
    ax.set_xticklabels(
        [c+': p='+str(p) for c,p in zip(column_names,pvals)])
    if outfilename:
        plt.savefig(outfilename)
    else:
        plt.show()
############################################################################

def main():
    comparator = Sentiment_Comparator(hi_lo_files,read_utterances,vadersentiment)
    #comparator = Sentiment_Comparator(hi_lo_files,read_sentences,vadersentiment)
    grp_avg = comparator.calc_group_mean()
    draw_group_mean_sentiments(grp_avg,
        comparator.column_names,
        ['ro-','r--','r-','r.-','bo-','b--','b-','b.-'])
        #,outfilename='./plots/Ensemble_Avg_Sent.pdf')
    time_avg,pvals = comparator.calc_time_mean()
    draw_time_mean_sentiments(time_avg,
        comparator.column_names,
        pvals)#,outfilename='./plots/Time_Avg_Sent.pdf')
    



if __name__ == '__main__':
    main()