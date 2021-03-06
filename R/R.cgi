#!/usr/bin/env perl

$\ = "\n";
use strict;
use warnings;
use CGI;
use CGI::Carp qw(fatalsToBrowser);
use Time::HiRes;
use Data::Dumper;
use Statistics::R;
use lib "../Scripts/pm";
use MapGen;
use ActionMongoDB;
use File::Copy 'copy';
use Archive::Zip;
use Errno ();
use JSON;

## R start set
my $R = Statistics::R->new();
$R->startR;
my $start_time = Time::HiRes::time;
##.

## CGI start set
my $cgi = new CGI;
my $InputData = decode_json( $cgi->param("data") );
print "Content-type: text/html;charset=utf-8;\n\n";
##.

## Mongo DB start set
my $client = MongoDB::MongoClient->new();
$client->authenticate('Carpesys', 't11881tm', 'taiyo1102');
my $database = $client->get_database('Carpesys');
my $collection = $database->get_collection('Element');
my $collection2 = $database->get_collection('Mapping_Data');
##.

## mapping.data parsing(/R/mapping.data)
##

my $Mapping_ID = ((time % 1296000) * 10 + int(rand(10)) + 1048576);
my @Mapping_Pathways;

## create Mapping DATA Directory(Graphs)
unless (mkdir ("./$Mapping_ID", 0755) or $! == Errno::EEXIST){
  die "failed to create dir:./$Mapping_ID:$!";
}
##.

my %JSON;

foreach my $hash (@$InputData){

  my %Mapping_Switch = (
			Graph_Mapping => 0,
			Intensity_Mapping => 0,
			Label_Mapping => 0
		       );
  
  
  my $query_id = $$hash{'name'};
  
  next if $query_id eq ''; # <- TASK: Error log

  ### Graph Mapping System
  ##.
  my $graph_type = lc $$hash{'type'};


  ## retrieve time series
  my $frequency =
    join ', ',
    map { $$hash{ $_->[0] } } ## TASK: Checker subroutine
    sort { $a->[1] <=> $b->[1] }
    map{ [$_, /^t(\d+)$/] }
    map{$$hash{$_}=~ s/^$/NA/;$_}
    ( grep /^t\d+$/, keys %$hash );
  
  my $time = '1:'.scalar(grep /^t\d+$/, keys %$hash);
  
  if($frequency =~ /[0-9]/){
    $Mapping_Switch{'Graph_Mapping'} = 1;
  }
  ##.

  ## Intensity Mapping

  my $element_color;
  my $i_color = $$hash{'i_color'};
  if( $i_color =~ /^[0-9]+$/ ){
    my @from_color = (255, 0, 0);
    my @to_color = (0, 255, 0);
    $element_color = unpack("H6", pack("C3", map{ (($to_color[$_] - $from_color[$_]) * $i_color/100) + $from_color[$_]} (0..2) ) );
    $element_color = '#'.$element_color;
    $Mapping_Switch{'Intensity_Mapping'} = 1;
  }else{
    ## Error: color is unvalid format
  }
  ##.


  ## Occurs when all mapping switches are zero
  next if $Mapping_Switch{'Intensity_Mapping'} == 0 && $Mapping_Switch{'Graph_Mapping'} == 0;
  ##.
  
  my $object;
  if($query_id =~ m/^[CDG]/){

    ##MongoDB search Get information of $query_id
    ##
    ## Variable list
    ## .@Mapping_Pathway => KEGG-Pathway ID
    ## .latlng

    $object = $collection->find({'Meta.cpd' => "$query_id"});

    unless($object->next){ ##Error Process. Occurs when the MongoDB search failed.
      $R->stopR();
      die "Not found $query_id in Database"; #<- TASK: Error log
    }

    while (my $record = $object->next){
      my $push2JSON = {};

      my @coords;

      ##created directory( e.g. /[ID]/00010/ ) for mapping datas
      push @Mapping_Pathways, $$record{'Pathway'};
      unless (mkdir ("./$Mapping_ID/$$record{'Pathway'}") or $! == Errno::EEXIST){
	die "failed to create dir:./$Mapping_ID:$!";
      }
      #.
      ## Get latlng data
      if ($$record{'Shape'} eq 'Rectangle') { ## Shape that applies to this condition is very ""LOW""
	@coords = ( "$$record{'latlng'}{'sw_lat'}", "$$record{'latlng'}{'sw_lng'}", "$$record{'latlng'}{'ne_lat'}", "$$record{'latlng'}{'ne_lng'}");
      } elsif ($$record{'Shape'} eq 'Circle') { ## Shape that applies to this condition is very ""OFTEN""
	@coords =  ( "$$record{'latlng'}{'lat'}", "$$record{'latlng'}{'lng'}" , "$$record{'latlng'}{'lat'}", "$$record{'latlng'}{'lng'}" );
      }
      #.

      
      $push2JSON->{'sw_latlng'} =  ["$coords[0]", "$coords[1]"];
      $push2JSON->{'ne_latlng'} = ["$coords[2]", "$coords[3]"];
      
      

      if($Mapping_Switch{'Intensity_Mapping'} == 1){
	$push2JSON->{'i_color'} = $element_color;
      }

      $push2JSON->{'Graph_Path'} = "${Mapping_ID}/$$record{'Pathway'}/${query_id}.png";

      push @{ $JSON{"Data"}{'map'.$$record{'Pathway'}} }, $push2JSON;

#      push @{ $JSON{"Data"}{'map'.$$record{'Pathway'}} }, {
#							   "Graph_Path" => "${Mapping_ID}/$$record{'Pathway'}/${query_id}.png",
#							   "sw_latlng" => ["$coords[0]", "$coords[1]"],
#							   "ne_latlng" => ["$coords[2]", "$coords[3]"]
#							  };
      
    }

  }elsif ($query_id =~ m/^([RK])/){
    my $id = $1;

    if($id eq 'K'){
      $object = $collection->find({'Meta.KEGG_ORTHOLOGY' => "$query_id"});
    }elsif( $id eq 'R'){
      $object = $collection->find({'Meta.KEGG_REACTION' => "$query_id"});
    }

    ## change => latlng じゃなくて xy値を持ってくる．
    while(my $record = $object->next){
      my $push2JSON = {};
      my @coords;
      push @Mapping_Pathways, $$record{'Pathway'};
      
      ##created directory( e.g. /[ID]/00010/ ) for mapping datas
      unless (mkdir ("./$Mapping_ID/$$record{'Pathway'}") or $! == Errno::EEXIST) {
	die "failed to create dir:./$Mapping_ID:$!";
      }
      ##.

      my ($sw_x, $sw_y, $ne_x, $ne_y);
      my ($sw_lat, $sw_lng, $ne_lat, $ne_lng);
      
      if ($$record{'Shape'} eq 'Rectangle') {
	
	($sw_x, $sw_y, $ne_x, $ne_y) = ("$$record{'xy'}{'sw_x'}", "$$record{'xy'}{'sw_y'}" , "$$record{'xy'}{'ne_x'}", "$$record{'xy'}{'ne_y'}" );


	if($Mapping_Switch{'Intensity_Mapping'} == 1){ # fill in circle
	  $push2JSON->{'i_LatLng'}->{'sw_latlng'} = [&Generator::xy2latlng($sw_x, $sw_y)];
	  $push2JSON->{'i_LatLng'}->{'ne_latlng'} = [&Generator::xy2latlng($ne_x, $ne_y)];
	}

	##これを足がかりとする．他の変更は一斉に．
	##latlngをxyに変換し画像サイズに設定の上またlatlng値に戻す．
	## swを固定する．つまり右上にはみ出た画像を貼ることになる．

	my $rect_width = $ne_x - $sw_x;
	$ne_y = $sw_y -  $rect_width;

	($sw_lat, $sw_lng) = (&Generator::xy2latlng($sw_x, $sw_y));
	($ne_lat, $ne_lng) = (&Generator::xy2latlng($ne_x, $ne_y) );

	##.
      } elsif ($$record{'Shape'} eq 'Circle') {

	if($Mapping_Switch{'Intensity_Mapping'} == 1){ # fill in circle
	  $push2JSON->{'i_LatLng'}->{'sw_latlng'} = ["$$record{'latlng'}{'lat'}", "$$record{'latlng'}{'lng'}"];
	}

	($sw_lat, $sw_lng, $ne_lat, $ne_lng) =  ( (&Generator::xy2latlng("$$record{'xy'}{'x'}", "$$record{'xy'}{'y'}")), (&Generator::xy2latlng("$$record{'xy'}{'x'}", "$$record{'xy'}{'y'}")) );

      }

      $push2JSON->{'sw_latlng'} =  ["$sw_lat", "$sw_lng"];
      $push2JSON->{'ne_latlng'} =  ["$ne_lat", "$ne_lng"];

      if($Mapping_Switch{'Intensity_Mapping'} == 1){
	$push2JSON->{'i_color'} = $element_color;
      }

      if($Mapping_Switch{'Graph_Mapping'} == 1){
	$push2JSON->{'Graph_Path'} = "${Mapping_ID}/$$record{'Pathway'}/${query_id}.png";
      }

      push @{ $JSON{"Data"}{'map'.$$record{'Pathway'}} }, $push2JSON;
    }
  }


  my $return_num = &R_Graph($query_id, $Mapping_ID, $graph_type, $time,$frequency, \@Mapping_Pathways);

  if ($return_num = 0){ ## Occurs when &R_Graph failed
    $R->stopR();
    printf("0.3f", Time::HiRes::time - $start_time);
    die "$query_id: Generate Graph failed\n";
  }
  ($query_id, $graph_type, $frequency) = undef;
  @Mapping_Pathways = ();
  
  
  ## Insert in MongoDB "Mapping_Data" collection
  #$collection2->insert($insert);
  ##

=pod

## Create a Zip file of Mapping Data
my $zip = Archive::Zip->new();
$zip->addTree( "${Mapping_ID}" );
map{$_->desiredCompressionMethod( 'COMPRESSION_LEVEL_BEST_COMPRESSION' )} $zip->members();
$zip->writeToFileNamed( "${Mapping_ID}/${Mapping_ID}.zip" );
##.

=cut
  
}


$R->stopR();

$JSON{'Mapping_ID'} = "$Mapping_ID";

=pod
my $insert;

$insert .= qq|{|;
$insert .=  qq( "Mapping_ID":"$Mapping_ID", );
$insert .=  qq( "Data":{);

while (my ($key, $value) = each(%JSON)) {
  $value =~ s/,\n$//g;
  $insert .= qq|"map$key" : [$value],|;
}
$insert =~ s/,$//;
$insert .= qq(});
$insert .= qq|}|;
$insert =~ s/\n//g;

# result for mapping(test)
print $insert;
#.
=cut

print encode_json(\%JSON);
#$insert = decode_json($insert);


sub R_Graph{
  my $R_script;
  my ($Query_ID, $Mapping_ID, $Graph_Type, $time, $freq, $Mapping_Pathways) = ($_[0], $_[1], $_[2], $_[3], $_[4], $_[5]);
  my $first_dir = shift @$Mapping_Pathways;
  my $file_from = "./${Mapping_ID}/${first_dir}/${Query_ID}.png";

  ## Data sets
  $R->send(qq`Data = data.frame( Time = c(${time}), Frequency = c(${freq}) )`);
  ##.
  $R->send(qq`png(file="${file_from}", width=200, height=200, bg="transparent", pointsize="10.5");`);
  $R->send(q`par(mar=c(1.4,2.0,0.5,0),  family="Times New Roman")`); ##mar[1]=below, mar[2]=left, mar[3]=above, mar[4]=right


  
  if ($Graph_Type eq 'bar') {	## Bar plot
    $R->send(q`barplot(Data$Frequency, col="black", ylim=c(0,100), yaxp=c(0,100,5), yaxt="n", mgp=c(0,0,0), names.arg=Data$Time)`);
    $R->send(q`axis(2, mgp=c(0,0.6,0), las=1, cex.axis=1.2)`); # y axis options
#    $R->send(qq`title(main="${Query_ID}", line=0.4, cex.main=1)`);
    
  }elsif ($Graph_Type eq 'line') { ## Line plot

    $R->send(q`plot(Data$Frequency,  type="l", col="black", lty=1, lwd=11, pch=20, bty="n", ylim=c(0,100), yaxp=c(0,100,5), yaxt="n",xaxt="n", ann=F )`);
    $R->send(q`axis(2, mgp=c(0,0.6,0), las=1, cex.axis=1.2)`); # y axis options
    $R->send(q`axis(1, mgp=c(0,0.4,0), Data$Time, cex.axis=0.9)`); # x axis options
#    $R->send(qq`title(main="${Query_ID}", line=0.4, cex.main=1.2)`);

  } elsif ($Graph_Type eq 'group') {
  }
  my $ret = $R->read;
  $R->send(qq`dev.off();`);

  ## Copy graph in other pathway
  for my $dir (@$Mapping_Pathways) {
    next if -e "./${Mapping_ID}/${dir}/${Query_ID}.png";
    my $file_to = "./${Mapping_ID}/${dir}/";
    copy($file_from, $file_to) or die "Cannot copy $file_from to $file_to: $!";
  }
  ##
  
  return 1;			## successful!!
  
}



__END__
{
  "Mapping_ID":"5122560",
    "Data":{
      "00230":[
	       {
		"ne_latlng":[
			     "12.4840331592034",
			     "149.36170212766"],
		"sw_latlng":[
			     "3.0598321005346",
			     "139.838987924094"],
		"Graph_Path":"5122560/00230/K03043.png"
	       },{"ne_latlng":["22.9189703382635","-114.997124784359"],"sw_latlng":["13.8948761203052","-124.519838987924"],"Graph_Path":"5122560/00230/K03043.png"},{"Graph_Path":"5122560/00230/K03046.png","sw_latlng":["3.0598321005346","139.838987924094"],"ne_latlng":["12.4840331592034","149.36170212766"]},{"Graph_Path":"5122560/00230/K03046.png","sw_latlng":["13.8948761203052","-124.519838987924"],"ne_latlng":["22.9189703382635","-114.997124784359"]}],"03020":[{"Graph_Path":"5122560/03020/K03043.png","ne_latlng":["-8.63514723865846","-139.7542997543"],"sw_latlng":["-27.8462366447398","-160.09828009828"]},{"Graph_Path":"5122560/03020/K03046.png","sw_latlng":["-34.2806504458716","-160.09828009828"],"ne_latlng":["-15.97534308768","-139.7542997543"]}],"00240":[{"sw_latlng":["38.8300460852731","-114.799154334038"],"ne_latlng":["47.3322534664842","-103.128964059197"],"Graph_Path":"5122560/00240/K03043.png"},{"Graph_Path":"5122560/00240/K03043.png","sw_latlng":["12.6635149286002","-114.038054968288"],"ne_latlng":["23.7291226984706","-102.367864693446"]},{"ne_latlng":["47.3322534664842","-103.128964059197"],"sw_latlng":["38.8300460852731","-114.799154334038"],"Graph_Path":"5122560/00240/K03046.png"},{"Graph_Path":"5122560/00240/K03046.png","ne_latlng":["23.7291226984706","-102.367864693446"],"sw_latlng":["12.6635149286002","-114.038054968288"]}]}}
  { "Mapping_ID":"0000000",

    "Data":{
      #      ..
      "map04910" : [
		    {
	"sw_xy"     <=    "sw_latlng" : [
				    "-66.3815962885395",
				    "-2.83817427385912"
				   ],
	"ne_xy"	  <=   "ne_latlng" : [
				    "-68.3355742069462",
				    "-16.5809128630707"
				   ],
		     "Graph_Path" : "7432847/04910/R02584.png"
		    },
		    {
		     "sw_latlng" : [
				    "-4.52057567282767",
				    "-132.796680497925"
				   ],
		     "ne_latlng" : [
				    "-9.55944925669965",
				    "-146.539419087137"
				   ],
		     "cn_latlng" : [
				   ],
		     "Graph_Path" : "7432847/04910/R02584.png",
		     "type": "rect" ## "circle"
		     "i_color" : "#ffffff"
		    }
		   ]#,
	#		       ..
    }
  }


