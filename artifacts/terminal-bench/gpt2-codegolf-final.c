#include<stdio.h>
#include<stdlib.h>
#include<string.h>
#include<math.h>
#include<fcntl.h>
#include<sys/mman.h>
#include<sys/stat.h>
#define V 50257
#define C 768
#define L 12
#define H 12
#define D 64
#define P 1024
#define F float
#define I int
F*w,*wte,*wpe,*kc[L],*vc[L];
F*lg[L],*lb[L],*cw[L],*cb[L],*pw[L],*pb[L],*l2g[L],*l2b[L],*fw[L],*fb[L],*p2w[L],*p2b[L],*lfg,*lfb;
void lc(char*f){I fd=open(f,0);struct stat s;fstat(fd,&s);w=mmap(0,s.st_size,1,2,fd,0);F*p=w;
I m[L]={0,1,10,11,2,3,4,5,6,7,8,9};for(I i=0;i<L;i++){I l=m[i];F*lw=p+i*7087872;
cb[l]=lw;lw+=2304;cw[l]=lw;lw+=C*3*C;pb[l]=lw;lw+=C;pw[l]=lw;lw+=C*C;lb[l]=lw;lw+=C;
lg[l]=lw;lw+=C;l2b[l]=lw;lw+=C;l2g[l]=lw;lw+=C;fb[l]=lw;lw+=4*C;fw[l]=lw;lw+=C*4*C;p2b[l]=lw;lw+=C;p2w[l]=lw;lw+=4*C*C;}
F*t=p+L*7087872;lfb=t;lfg=t+C;wpe=t+2*C;wte=t+2*C+P*C;}
char b2u[256][4];
I b2p[256],p2byte[256];
short mr[150000*2];I nm;
I*hk,*hv;I hs=262144;char*sp;I spa;
I hf(char*s){unsigned h=0;while(*s)h=h*31+*s++;return h&(hs-1);}
void hi(char*s,I v){I i=hf(s);while(hk[i]!=-1){if(!strcmp(sp+hk[i],s)){hv[i]=v;return;}i=(i+1)&(hs-1);}
I o=spa;while(*s)sp[spa++]=*s++;sp[spa++]=0;hk[i]=o;hv[i]=v;}
I hg(char*s){I i=hf(s);while(hk[i]!=-1){if(!strcmp(sp+hk[i],s))return hv[i];i=(i+1)&(hs-1);}return-1;}
void ib(){I i,pos=0,r=0;
for(i=33;i<=126;i++){b2p[i]=pos;p2byte[pos]=i;b2u[i][0]=i;pos++;}
for(i=161;i<=172;i++){b2p[i]=pos;p2byte[pos]=i;b2u[i][0]=192+(i>>6);b2u[i][1]=128+(i&63);pos++;}
for(i=174;i<=255;i++){b2p[i]=pos;p2byte[pos]=i;b2u[i][0]=192+(i>>6);b2u[i][1]=128+(i&63);pos++;}
for(i=0;i<=32;i++){b2p[i]=pos;p2byte[pos]=i;I c=256+r++;b2u[i][0]=192+(c>>6);b2u[i][1]=128+(c&63);pos++;}
b2p[127]=pos;p2byte[pos]=127;{I c=256+r++;b2u[127][0]=192+(c>>6);b2u[127][1]=128+(c&63);pos++;}
for(i=128;i<=160;i++){b2p[i]=pos;p2byte[pos]=i;I c=256+r++;b2u[i][0]=192+(c>>6);b2u[i][1]=128+(c&63);pos++;}
b2p[173]=pos;p2byte[pos]=173;{I c=256+r++;b2u[173][0]=192+(c>>6);b2u[173][1]=128+(c&63);pos++;}
for(i=0;i<256;i++)hi(b2u[i],b2p[i]);}
void lv(char*f){FILE*fi=fopen(f,"r");if(!fi)return;char l[4096],a[2048],b[2048];fgets(l,4096,fi);nm=0;
while(fgets(l,4096,fi)&&nm<150000){if(sscanf(l,"%s%s",a,b)==2){I ia=hg(a),ib=hg(b);if(ia<0||ib<0)continue;
mr[nm*2]=ia;mr[nm*2+1]=ib;char t[4096];strcpy(t,a);strcat(t,b);hi(t,256+nm);nm++;}}fclose(fi);}
I en(char*tx,I*tk){I n=0;for(char*p=tx;*p;p++)tk[n++]=b2p[(unsigned char)*p];
for(I i=0;i<nm;i++){I a=mr[i*2],b=mr[i*2+1];I j=0;
for(I k=0;k<n;k++){if(k<n-1&&tk[k]==a&&tk[k+1]==b){tk[j++]=256+i;k++;}else tk[j++]=tk[k];}n=j;}return n;}
void ln(F*x,F*g,F*b,I n){F m=0,v=0;for(I i=0;i<n;i++)m+=x[i];m/=n;
for(I i=0;i<n;i++){F d=x[i]-m;v+=d*d;}v=sqrt(v/n+1e-5);for(I i=0;i<n;i++)x[i]=g[i]*(x[i]-m)/v+b[i];}
void mv(F*o,F*x,F*w,F*b,I n,I d){for(I j=0;j<d;j++){F val=b?b[j]:0;
for(I i=0;i<n;i++)val+=x[i]*w[i*d+j];o[j]=val;}}
void ge(F*x,I n){for(I i=0;i<n;i++){F v=x[i];x[i]=.5*v*(1+tanhf(.79788456*(v+.044715*v*v*v)));}}
void fwd1(F*x,I pos){for(I l=0;l<L;l++){
F nm[C],qkv[3*C];memcpy(nm,x,C*4);ln(nm,lg[l],lb[l],C);mv(qkv,nm,cw[l],cb[l],C,3*C);
memcpy(kc[l]+pos*C,qkv+C,C*4);memcpy(vc[l]+pos*C,qkv+2*C,C*4);
F ao[C];memset(ao,0,C*4);F sc=1./sqrtf(D);
for(I h=0;h<H;h++){F*q=qkv+h*D;F s[P];F mx=-1e9;
for(I t=0;t<=pos;t++){F v=0;F*k=kc[l]+t*C+h*D;for(I j=0;j<D;j++)v+=q[j]*k[j];v*=sc;s[t]=v;if(v>mx)mx=v;}
F sm=0;for(I t=0;t<=pos;t++){s[t]=expf(s[t]-mx);sm+=s[t];}
for(I t=0;t<=pos;t++){F w=s[t]/sm;F*v=vc[l]+t*C+h*D;for(I j=0;j<D;j++)ao[h*D+j]+=w*v[j];}}
F po[C];mv(po,ao,pw[l],pb[l],C,C);for(I j=0;j<C;j++)x[j]+=po[j];
memcpy(nm,x,C*4);ln(nm,l2g[l],l2b[l],C);F fh[4*C];mv(fh,nm,fw[l],fb[l],C,4*C);ge(fh,4*C);
mv(po,fh,p2w[l],p2b[l],4*C,C);for(I j=0;j<C;j++)x[j]+=po[j];}
ln(x,lfg,lfb,C);}
void dc(I tk,char*buf){if(tk<256){buf[0]=p2byte[tk];buf[1]=0;return;}
I i=tk-256;if(i>=nm){buf[0]=0;return;}char l[2048],r[2048];dc(mr[i*2],l);dc(mr[i*2+1],r);strcpy(buf,l);strcat(buf,r);}
I main(I ac,char**av){if(ac!=4)return 1;
hk=calloc(hs,4);hv=malloc(hs*4);for(I i=0;i<hs;i++)hk[i]=-1;sp=malloc(4000000);spa=0;
ib();lv(av[2]);lc(av[1]);
for(I l=0;l<L;l++){kc[l]=calloc(P*C,4);vc[l]=calloc(P*C,4);}
I tk[2048];I nt=en(av[3],tk);if(nt<1)tk[nt++]=0;
F x[C];
for(I t=0;t<nt;t++){for(I i=0;i<C;i++)x[i]=wte[tk[t]*C+i]+wpe[t*C+i];fwd1(x,t);}
for(I g=0;g<20;g++){F mx=-1e9;I bi=0;
for(I i=0;i<V;i++){F s=0;for(I j=0;j<C;j++)s+=x[j]*wte[i*C+j];if(s>mx){mx=s;bi=i;}}
tk[nt++]=bi;I pos=nt-1;for(I i=0;i<C;i++)x[i]=wte[bi*C+i]+wpe[pos*C+i];fwd1(x,pos);}
char ob[8192]="",tb[4096];for(I i=nt-20;i<nt;i++){dc(tk[i],tb);strcat(ob,tb);}puts(ob);return 0;}
