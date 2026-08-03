set terminal pngcairo size 900,600 enhanced font "Helvetica,16"
set output "thickness_scan.png"
set xlabel "Foil half-thickness (mm)"
set ylabel "Run1A CE  S / sqrt(B)"
set grid
set key bottom right
set xrange [0:0.16]
set yrange [2.7:4.0]
set arrow from 0.0528,2.7 to 0.0528,4.0 nohead lc rgb "#888888" dt 2
set label "config\\_v00 baseline" at 0.0528,3.85 right offset -0.5,0 textcolor rgb "#666666"
set arrow from 0.025,3.31 to 0.155,3.31 nohead lc rgb "#888888" dt 3
set label "baseline 3.31" at 0.140,3.34 right textcolor rgb "#666666"
plot "thickness_data.tsv" using 2:3:(sprintf("%.2f", $3)) \
        with labels offset 0,1 font "Helvetica,12" textcolor rgb "#444444" notitle, \
     "" using 2:3 with linespoints lw 2 ps 1.6 pt 7 lc rgb "#1f77b4" title "1D LLM-greedy scan"
